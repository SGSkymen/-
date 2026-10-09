import io
import json
import time
import logging
import threading
from typing import Dict, List, Any, Optional
import pandas as pd


from backend.config import (
    DB_PATH, RISK_LOW_THRESHOLD, RISK_HIGH_THRESHOLD, CACHE_TTL_SECONDS,
    DEFAULT_PAGE_SIZE, SYNTHETIC_ROWS, SYNTHETIC_CHURN_RATE, EXPORT_DIR,
    BASE_MODEL_PATH, setup_logging,
)
from backend.database import Database, CLIENT_FIELDS
from backend.data_generator import generate_synthetic_clients
from backend.ml_model import ChurnModel


logger = setup_logging()
COLUMN_MAPPING = {
    "фио": "fio","ф.и.о.":"fio","имя клиента":"fio",
    "номер счета": "account_number","номер счёта":"account_number","счет":"account_number",
    "номер карты": "card_number","карта":"card_number",
    "возраст": "age",
    "сумма вклада": "deposit_amount","сумма депозита":"deposit_amount","вклад":"deposit_amount",
    "текущая ставка": "current_rate","ставка":"current_rate",
    "рыночная ставка": "market_rate","ставка рынка":"market_rate",
    "количество входов": "login_count","логины":"login_count",
    "дней до окончания": "days_to_maturity","срок до окончания":"days_to_maturity",
    "дней с последнего входа": "days_since_last_login",
    "количество продуктов": "product_count","продукты":"product_count",
    "регион": "region",
    "отток": "churn","churn":"churn",
    "дата последней активности":"last_activity_date",
}

INT_FIELDS = {"age", "login_count", "days_to_maturity", "days_since_last_login","product_count", "churn"}
FLOAT_FIELDS = {"deposit_amount", "current_rate", "market_rate", "rate_diff"}
def _cache_key(method: str, *args) -> str:
    return f"{method}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}"




class Api:
    def __init__(self):
        self.db = Database(DB_PATH)
        self.model = ChurnModel()
        self._cache: Dict[str,tuple] = {}  
        self._cache_lock = threading.Lock()
        self._window = None
        self._bootstrap()


    def _bootstrap(self):
        if self.db.is_empty():
            logger.info("БД пуста — генерация базовой синтетической выборки")
            records = generate_synthetic_clients(SYNTHETIC_ROWS, SYNTHETIC_CHURN_RATE)
            self.db.batch_insert(records)
            df = self._load_training_frame()
            self.model.train(df, init_model_path=None, save_as="base")
            self._rescore_all()
        else:
            loaded = self.model.load_existing_or_none()
            if not loaded:
                logger.info("Модель не найдена, но БД не пуста — переобучение с нуля")
                df = self._load_training_frame()
                self.model.train(df, init_model_path=None, save_as="base")
                self._rescore_all()


    def set_window(self, window):
        self._window = window


    def _push_progress(self,percent: int,label: str =""):
        if self._window is None:
            return
        try:
            self._window.evaluate_js(
                f"window.onBackendProgress && window.onBackendProgress({percent},{json.dumps(label,ensure_ascii=False)})"
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить прогресс в UI: {e}")


    def _cache_get(self,key:str):
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            ts,value = entry
            if time.time()- ts>CACHE_TTL_SECONDS:
                del self._cache[key]
                return None
            return value

    def _cache_set(self,key:str,value):
        with self._cache_lock:
            self._cache[key]= (time.time(),value)


    def clear_cache(self)-> Dict:
        with self._cache_lock:
            self._cache.clear()
        return {"status":"ok","message":"Кэш очищен"}


    def _load_training_frame(self)-> pd.DataFrame:
        rows = self.db.fetch_all_for_training()
        return pd.DataFrame([dict(r)for r in rows])


    def _rescore_all(self):
        rows = self.db.fetch_ids_for_scoring()
        if not rows:
            return
        df = pd.DataFrame([dict(r)for r in rows]);ids = df["id"].tolist()
        probs = self.model.predict_proba(df)
        self.db.update_churn_probabilities(list(zip(ids,[float(p)for p in probs])))


    def import_json(self, json_data: str) -> Dict:
        try:
            self._push_progress(5,"Разбор JSON")
            raw_records = json.loads(json_data)
            if not isinstance(raw_records, list):
                return {"status":"error","message":"Ожидался JSON-массив объектов"}
            if len(raw_records) == 0:
                return {"status": "error", "message": "Пустой набор данных"}


            self._push_progress(15,"Маппинг колонок и валидация")
            normalized = [self._normalize_record(r)for r in raw_records];valid_records = [r for r in normalized if r.get("fio")]
            skipped = len(normalized) - len(valid_records)


            if not valid_records:
                return {"status": "error", "message": "Не найдено ни одной валидной записи (нет ФИО)"}
            self._push_progress(35, "Запись в базу данных")
            # Батч-вставка по 1000 записей внутри транзакции (см. Database.batch_upsert)
            upserted = self.db.batch_upsert(valid_records, batch_size=1000)


            self._push_progress(55,"Дообучение модели на новых данных")
            df = self._load_training_frame(); metrics = self.model.incremental_train(df)
            self._push_progress(85,"Обновление вероятностей оттока")
            self._rescore_all()
            self.clear_cache()
            self._push_progress(100,"Готово")


            return {"status":"ok","imported": upserted,"skipped": skipped,"total_clients": self.db.count_clients(),"metrics": metrics,}
        except json.JSONDecodeError as e:
            logger.exception("Ошибка разбора JSON при импорте")
            return {"status":"error","message":f"Некорректный JSON: {e}"}
        except Exception as e:
            logger.exception("Ошибка импорта")
            return {"status":"error","message":f"Ошибка импорта: {e}"}

    def _normalize_record(self,raw:Dict)-> Dict:
        rec: Dict[str,Any] = {}
        for key, value in raw.items():
            norm_key = COLUMN_MAPPING.get(str(key).strip().lower(), None)
            if norm_key is None:
                if str(key).strip().lower()in CLIENT_FIELDS:
                    norm_key = str(key).strip().lower()
                else:
                    continue
            rec[norm_key] = value


        for field in INT_FIELDS:
            if field in rec:
                rec[field] = self._safe_int(rec[field])
        for field in FLOAT_FIELDS:
            if field in rec:
                rec[field] = self._safe_float(rec[field])


        if "rate_diff" not in rec and "market_rate" in rec and "current_rate" in rec:
            try:
                rec["rate_diff"] = round(float(rec["market_rate"]) - float(rec["current_rate"]), 2)
            except (TypeError, ValueError):
                rec["rate_diff"] = None

        rec.setdefault("churn",0)
        rec.setdefault("region","Регионы")
        return rec


    @staticmethod
    def _safe_int(value)-> Optional[int]:
        try:
            return int(float(value))
        except (TypeError,ValueError):
            return None
    @staticmethod
    def _safe_float(value)-> Optional[float]:
        try:
            return float(value)
        except (TypeError,ValueError):
            return None


    def get_dashboard_data(self)-> Dict:
        key = _cache_key("get_dashboard_data")
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        agg = self.db.get_dashboard_aggregates()
        result = {
            "total_portfolio": round(agg.get("total_portfolio",0) or 0,2),
            "total_clients": agg.get("total_clients",0) or 0,
            "high_risk_count": agg.get("high_risk_count",0) or 0,
            "avg_churn_percent": round((agg.get("avg_risk",0) or 0)*100,2),
            "model_accuracy": self.model.last_metrics.get("accuracy"),
            "model_roc_auc": self.model.last_metrics.get("roc_auc"),
            "risk_distribution": self.db.get_risk_distribution(),
        }
        self._cache_set(key,result)
        return result


    def get_clients(self,filter_type: str = "default",search_query: str = "",page: int = 1,limit: int = DEFAULT_PAGE_SIZE,last_id: int = 0)-> Dict:
        key = _cache_key("get_clients", filter_type, search_query, last_id, limit)
        cached = self._cache_get(key)
        if cached is not None:
            return cached


        records, has_more = self.db.get_clients(filter_type,search_query,last_id,limit)
        total = self.db.total_count_for_query(search_query)
        for r in records:
            r["risk_zone"] = self._risk_zone(r.get("churn_probability") or 0)

        result = {"records": records,"has_more": has_more,"total": total,"next_cursor": records[-1]["id"]if records else last_id,}
        self._cache_set(key, result)
        return result


    def search_client(self, query: str) -> Dict:
        records = self.db.search_client(query)
        for r in records:
            r["risk_zone"] = self._risk_zone(r.get("churn_probability") or 0)
        return {"records": records, "count": len(records)}


    def get_monthly_stats(self) -> Dict:
        key = _cache_key("get_monthly_stats")
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        rows = self.db.get_monthly_stats(12)
        result = {"labels": [r["month"] for r in rows],"new_clients": [r["new_clients"] for r in rows],"total_deposits": [round(r["total_deposits"], 2) for r in rows],"avg_risk": [round((r["avg_risk"] or 0) * 100, 2) for r in rows],}
        self._cache_set(key, result)
        return result


    def get_risk_distribution(self) -> Dict:
        return self.db.get_risk_distribution()


    def retrain_model(self) -> Dict:
        try:
            self._push_progress(10, "Загрузка данных для переобучения")
            df = self._load_training_frame()
            if df.empty or df["churn"].nunique() < 2:
                return {"status": "error", "message": "Недостаточно данных для переобучения (нужны оба класса)"}

            self._push_progress(30, "Разделение на выборки и SMOTE")
            self._push_progress(50, "Обучение LightGBM")
            metrics = self.model.train(df, init_model_path=None, save_as="updated")
            self._push_progress(85, "Обновление вероятностей оттока")
            self._rescore_all()
            self.clear_cache()
            self._push_progress(100, "Готово")
            return {"status": "ok", "metrics": metrics}
        except Exception as e:
            logger.exception("Ошибка переобучения")
            return {"status": "error", "message": f"Ошибка переобучения: {e}"}


    def export_report(self) -> Dict:
        try:
            import os
            rows = self.db.fetch_all_for_export()
            if not rows:
                return {"status": "error", "message": "Нет данных для экспорта"}
            df = pd.DataFrame(rows)
            filename = f"vtb_report_{int(time.time())}.xlsx"
            path = os.path.join(EXPORT_DIR, filename)
            df.to_excel(path, index=False, engine="openpyxl")
            return {"status": "ok", "path": path, "rows": len(rows)}
        except Exception as e:
            logger.exception("Ошибка экспорта отчёта")
            return {"status": "error", "message": f"Ошибка экспорта: {e}"}


    @staticmethod
    def _risk_zone(prob: float) -> str:
        if prob > RISK_HIGH_THRESHOLD:
            return "red"
        if prob < RISK_LOW_THRESHOLD:
            return "green"
        return "yellow"


    def shutdown(self):
        self.db.close()
