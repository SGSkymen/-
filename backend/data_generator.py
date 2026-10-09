import random
import math
from datetime import datetime, timedelta
from typing import List, Dict


REGIONS = ["Москва", "СПБ", "Регионы"]
FIRST_NAMES_M = ["Александр", "Дмитрий", "Сергей", "Андрей", "Максим", "Иван", "Артём", "Никита"]
FIRST_NAMES_F = ["Елена", "Ольга", "Наталья", "Ирина", "Анна", "Мария", "Татьяна", "Светлана"]
LAST_NAMES = ["Иванов", "Петров", "Сидоров", "Смирнов", "Кузнецов", "Попов", "Волков", "Соколов","Морозов", "Новиков", "Фёдоров", "Егоров"]
PATRONYMIC_M = ["Александрович", "Дмитриевич", "Сергеевич", "Андреевич", "Иванович", "Николаевич"]
PATRONYMIC_F = ["Александровна", "Дмитриевна", "Сергеевна", "Андреевна", "Ивановна", "Николаевна"]


def _random_fio() -> str:
    is_male = random.random()< 0.5
    last = random.choice(LAST_NAMES)
    if is_male:
        first = random.choice(FIRST_NAMES_M)
        patronymic = random.choice(PATRONYMIC_M)
    else:
        last += "а"
        first = random.choice(FIRST_NAMES_F)
        patronymic = random.choice(PATRONYMIC_F)
    return f"{last} {first} {patronymic}"


def _random_account_number() -> str:
    return "40817"+"".join(str(random.randint(0,9)) for _ in range(15))


def _random_card_last4()-> str:
    return f"{random.randint(0,9999):04d}"


def _sigmoid(x: float) -> float:
    return 1.0/(1.0 + math.exp(-x))


def generate_synthetic_clients(n: int = 3000,target_churn_rate: float = 0.15,
                                seed: int = 42)-> List[Dict]:

    rng = random.Random(seed); random.seed(seed); records = []; hidden_scores = []

    for i in range(n):
        age = rng.randint(20,75)
        deposit_amount = round(rng.uniform(10_000,5_000_000) 2)
        current_rate = round(rng.uniform(4.0,12.0),2)
        market_rate = round(current_rate + rng.uniform(-3.0,5.0),2)
        rate_diff = round(market_rate - current_rate,2)
        login_count = max(0,int(rng.gauss(15,10)))
        days_since_last_login = max(0, int(rng.gauss(20,25)))
        days_to_maturity = rng.randint(0,720)
        product_count = rng.randint(1,6)
        region = rng.choice(REGIONS)


        z = (
            0.55 * (rate_diff / 3.0)                         # невыгодная ставка -> выше риск
            - 0.35 * (login_count / 15.0 - 1.0)               # мало логинов -> выше риск
            + 0.45 * (days_since_last_login / 20.0 - 1.0)     # давно не заходил -> выше риск
            - 0.30 * (days_to_maturity / 180.0 - 1.0)         # близкий срок -> выше риск (обратная связь ниже)
            + rng.gauss(0, 0.6)                                # шум
        )
        z += 0.4*(1.0 - min(days_to_maturity,365)/365.0)


        hidden_scores.append(z)
        last_activity_date = (datetime.now() - timedelta(days=days_since_last_login + rng.randint(0, 30))).strftime("%Y-%m-%d")
        records.append({
            "fio": _random_fio(),
            "account_number": _random_account_number(),
            "card_number": _random_card_last4(),
            "age": age,
            "deposit_amount": deposit_amount,
            "current_rate": current_rate,
            "market_rate": market_rate,
            "rate_diff": rate_diff,
            "login_count": login_count,
            "days_to_maturity": days_to_maturity,
            "days_since_last_login": days_since_last_login,
            "product_count": product_count,
            "region": region,
            "last_activity_date": last_activity_date,
        })


    sorted_scores = sorted(hidden_scores)
    cutoff_index = int(len(sorted_scores) * (1 - target_churn_rate))
    cutoff_index = min(max(cutoff_index, 0), len(sorted_scores) - 1)
    threshold = sorted_scores[cutoff_index]

    for rec, z in zip(records, hidden_scores):
        prob = _sigmoid((z - threshold) * 3.0)
        rec["churn"] = 1 if rng.random() < prob else 0
        rec["churn_probability"] = round(prob, 4)
    return records
