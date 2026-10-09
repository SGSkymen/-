import os
import logging
from typing import Dict, Tuple, Optional
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score, roc_auc_score,
)
from imblearn.over_sampling import SMOTE
from backend.config import LGBM_PARAMS, FEATURE_COLUMNS, BASE_MODEL_PATH, UPDATED_MODEL_PATH
logger = logging.getLogger("vtb_analytics")


class ChurnModel:
    def __init__(self):
        self.booster: Optional[lgb.Booster] = None
        self.feature_columns = FEATURE_COLUMNS
        self.last_metrics: Dict = {}
        self.model_path: Optional[str] = None


    def load_existing_or_none(self) -> bool:
        for path in (UPDATED_MODEL_PATH, BASE_MODEL_PATH):
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    model_str = f.read()
                self.booster = lgb.Booster(model_str=model_str)
                self.model_path = path
                logger.info(f"Загружена модель из {os.path.basename(path)} (через model_str, в обход fopen)")
                return True
        return False


    def _prepare_xy(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
        for col in self.feature_columns:
            if col not in df.columns:
                df[col] = 0
        df[self.feature_columns] = df[self.feature_columns].apply(
            pd.to_numeric, errors="coerce"
        ).fillna(0)
        X = df[self.feature_columns]
        y = df["churn"].astype(int) if "churn" in df.columns else None
        return X, y


    def train(self, df: pd.DataFrame, init_model: Optional[lgb.Booster] = None,
              save_as: str = "base") -> Dict:


        X, y = self._prepare_xy(df)
        X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=0.30, stratify=y, random_state=42)
        X_val, X_test, y_val, y_test = train_test_split(X_temp, y_temp, test_size=0.50, stratify=y_temp, random_state=42)


        try:
            if y_train.nunique() > 1 and y_train.value_counts().min() >= 2:
                smote = SMOTE(sampling_strategy="auto", random_state=42)
                X_train, y_train = smote.fit_resample(X_train, y_train)
            else:
                logger.warning("SMOTE пропущен: недостаточно данных одного из классов")
        except ValueError as e:
            logger.warning(f"SMOTE пропущен из-за ошибки: {e}")


        train_set = lgb.Dataset(X_train, label=y_train)
        val_set = lgb.Dataset(X_val, label=y_val, reference=train_set)
        booster = lgb.train(
            LGBM_PARAMS,
            train_set,
            num_boost_round=500,
            valid_sets=[train_set, val_set],
            valid_names=["train", "val"],
            init_model=init_model,
            callbacks=[
                lgb.early_stopping(stopping_rounds=30, verbose=False),
                lgb.log_evaluation(period=0),
            ],
        )



        best_iter = booster.best_iteration if booster.best_iteration and booster.best_iteration > 0 else None
        y_pred_proba = booster.predict(X_test, num_iteration=best_iter)
        y_pred = (y_pred_proba >= 0.5).astype(int)



        metrics = {
            "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
            "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
            "roc_auc": round(float(roc_auc_score(y_test, y_pred_proba)), 4)
                        if y_test.nunique() > 1 else None,
            "train_rows": int(len(X_train)),
            "val_rows": int(len(X_val)),
            "test_rows": int(len(X_test)),
        }



        importances = dict(zip(
            self.feature_columns,
            [int(v) for v in booster.feature_importance(importance_type="gain")],
        ))
        logger.info(f"Метрики обучения: {metrics}")
        logger.info(f"Важность признаков: {importances}")


        save_path = BASE_MODEL_PATH if save_as == "base" else UPDATED_MODEL_PATH
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        model_str = booster.model_to_string()
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(model_str)
        self.booster = booster
        self.model_path = save_path
        self.last_metrics = {**metrics, "feature_importance": importances}
        return self.last_metrics


    def incremental_train(self, df: pd.DataFrame)-> Dict:
        init_path = self.model_path
        return self.train(df, init_model_path=init_path, save_as="updated")


    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        if self.booster is None:
            raise RuntimeError("Модель не загружена/не обучена")
        X, _ = self._prepare_xy(df)
        return self.booster.predict(X, num_iteration=self._safe_best_iteration())


    def _safe_best_iteration(self)-> Optional[int]:
        bi = getattr(self.booster,"best_iteration",None)
        return bi if bi and bi > 0 else None
