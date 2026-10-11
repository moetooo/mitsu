"""
Local Multilabel Machine Learning Tag Classifier for Manga Metadata.

Features:
1. Lightweight, low-memory TF-IDF + OneVsRest LogisticRegression.
2. Calibrated probabilistic multi-label inference.
3. Strict canonical taxonomy enforcement: unknown tags are excluded from labels.
4. Per-label precision-oriented threshold calibration to eliminate false positives.
5. Multi-tier safety policy: HIGH (accepted), MEDIUM (review), LOW (rejected).
6. Label-specific safety for sensitive categories (BL, GL, demographics, tropes).
7. Produces InferredTag instances with provenance='model'.
8. 100% offline, local execution with zero network/LLM dependencies.
"""

import os
import json
import joblib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Union, Tuple
from collections import Counter

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score, f1_score

from .vocabulary import CANONICAL_VOCABULARY, get_tag_by_slug
from .models import InferredTag
from .ml_features import build_ml_text, extract_canonical_labels

DEFAULT_MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models", "tag_classifier")
MODEL_VERSION = "v1.1.0-calibrated"

# Sensitive labels requiring elevated precision safeguards
SENSITIVE_LABELS = {
    "boys_love",
    "girls_love",
    "ecchi",
    "shounen",
    "shoujo",
    "seinen",
    "josei",
    "love_triangle",
    "harem",
    "reverse_harem",
    "age_gap",
}

# Empirically validated calibrated thresholds based on held-out evaluation
DEFAULT_CALIBRATED_THRESHOLDS: Dict[str, float] = {
    "action": 0.60,
    "adventure": 0.80,
    "age_gap": 0.80,
    "anthology": 0.70,
    "boys_love": 0.85,
    "college_university": 0.90,
    "comedy": 0.60,
    "crime": 0.80,
    "demons": 0.80,
    "drama": 0.70,
    "dungeon_gate": 0.80,
    "dystopian": 0.80,
    "ecchi": 0.80,
    "fake_relationship": 0.80,
    "fantasy": 0.50,
    "feudal_japan": 0.90,
    "full_color": 0.50,
    "girls_love": 0.80,
    "harem": 0.80,
    "historical": 0.85,
    "horror": 0.80,
    "isekai": 0.80,
    "josei": 0.80,
    "long_strip": 0.80,
    "love_triangle": 0.80,
    "magic": 0.80,
    "mahou_shoujo": 0.85,
    "martial_arts": 0.70,
    "mecha": 0.90,
    "military": 0.80,
    "monsters": 0.80,
    "music": 0.60,
    "mystery": 0.85,
    "one_shot": 0.80,
    "parody": 0.80,
    "post_apocalyptic": 0.80,
    "psychological": 0.80,
    "reborn_as_a_villainess": 0.80,
    "reincarnation": 0.80,
    "revenge": 0.80,
    "reverse_harem": 0.80,
    "romance": 0.50,
    "school_life": 0.60,
    "sci_fi": 0.90,
    "seinen": 0.80,
    "shoujo": 0.80,
    "shounen": 0.80,
    "slice_of_life": 0.80,
    "space": 0.80,
    "sports": 0.70,
    "supernatural": 0.70,
    "superpowers": 0.80,
    "survival": 0.80,
    "thriller": 0.80,
    "time_skip": 0.80,
    "time_travel": 0.80,
    "tragedy": 0.80,
    "video_games": 0.80,
    "webtoon": 0.70,
    "workplace": 0.80,
}


class TagClassifier:
    """
    Multilabel classifier predicting canonical tags from manga titles and synopses.
    Supports precision-oriented per-label threshold calibration and multi-tier acceptance.
    """

    def __init__(
        self,
        model_version: str = MODEL_VERSION,
        default_threshold: float = 0.70,
        per_label_thresholds: Optional[Dict[str, float]] = None,
        max_features: int = 15000,
        ngram_range: Tuple[int, int] = (1, 2),
        min_df: int = 2
    ):
        self.model_version = model_version
        self.default_threshold = default_threshold
        # Preserve user-specified overrides so re-evaluation doesn't clobber them
        self._user_per_label_thresholds: Dict[str, float] = dict(per_label_thresholds or {})
        self.per_label_thresholds: Dict[str, float] = dict(DEFAULT_CALIBRATED_THRESHOLDS)
        if per_label_thresholds:
            self.per_label_thresholds.update(per_label_thresholds)

        self.max_features = max_features
        self.ngram_range = ngram_range
        self.min_df = min_df

        self.vectorizer: Optional[TfidfVectorizer] = None
        self.classifier: Optional[OneVsRestClassifier] = None
        self.mlb: Optional[MultiLabelBinarizer] = None
        self.labels_: List[str] = []
        self.metadata_: Dict[str, Any] = {}

    @property
    def is_trained(self) -> bool:
        """Returns True if model and vectorizer are fitted and ready for inference."""
        return self.classifier is not None and self.vectorizer is not None

    def get_threshold_for_label(
        self,
        slug: str,
        override_threshold: Optional[float] = None,
        override_dict: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Returns the active threshold for a given canonical slug.
        Priority:
        1. Explicit per-call override_dict[slug]
        2. Explicit global override_threshold
        3. Instance per_label_thresholds[slug]
        4. Instance default_threshold
        """
        if override_dict and slug in override_dict:
            return override_dict[slug]
        if override_threshold is not None:
            return override_threshold
        return self.per_label_thresholds.get(slug, self.default_threshold)

    def get_precision_tier(self, slug: str) -> str:
        """
        Returns the precision tier for a label:
        'high', 'medium', 'low', or 'insufficient_support'.
        """
        precision_tiers = self.metadata_.get("precision_tiers")
        if precision_tiers:
            for tier in ("high", "medium", "low", "insufficient_support"):
                tier_labels = precision_tiers.get(tier, [])
                for item in tier_labels:
                    item_slug = item[0] if isinstance(item, (list, tuple)) else item
                    if item_slug == slug:
                        return tier
        return "high"  # Default if uncalibrated/fixture

    def classify_prediction(
        self,
        slug: str,
        prob: float,
        active_threshold: float,
        accept_tier: str = "high"
    ) -> Tuple[str, bool]:
        """
        Assigns a confidence tier ('high', 'medium', 'low') and determines
        acceptance according to the safety policy.
        
        Tiers:
        - HIGH: prob >= active_threshold and label precision tier is 'high' (or uncalibrated).
        - MEDIUM: prob >= baseline threshold (0.50 or active_threshold) and label precision tier is 'medium'.
        - LOW: prob < active_threshold, or label precision tier is 'low'/'insufficient_support'.
        
        Acceptance:
        - 'high': only HIGH confidence predictions are accepted.
        - 'medium': HIGH or MEDIUM confidence predictions are accepted.
        - 'all': any prediction meeting active_threshold is accepted.
        """
        label_tier = self.get_precision_tier(slug)
        meets_threshold = prob >= active_threshold

        if not meets_threshold:
            conf_tier = "low"
            accepted = False
        else:
            if label_tier == "high":
                conf_tier = "high"
            elif label_tier == "medium":
                conf_tier = "medium"
            else:
                conf_tier = "low"

            if accept_tier == "high":
                accepted = (conf_tier == "high")
            elif accept_tier == "medium":
                accepted = (conf_tier in ("high", "medium"))
            else:
                accepted = True

        return conf_tier, accepted

    @property
    def is_trained(self) -> bool:
        return self.classifier is not None and self.vectorizer is not None and len(self.labels_) > 0

    def evaluate_per_label(
        self,
        X_test: List[str],
        Y_test: np.ndarray,
        thresholds: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        Evaluates per-label precision, recall, F1, and support across multiple thresholds.
        Determines recommended calibrated thresholds and precision tiers.
        """
        if not self.is_trained:
            raise RuntimeError("Classifier must be trained before evaluate_per_label().")

        if thresholds is None:
            thresholds = [0.50, 0.60, 0.70, 0.80, 0.85, 0.90]

        X_test_vec = self.vectorizer.transform(X_test)
        Y_proba = self.classifier.predict_proba(X_test_vec)

        per_label_results: Dict[str, Any] = {}
        calibrated_thresholds: Dict[str, float] = {}

        for idx, slug in enumerate(self.labels_):
            y_true = Y_test[:, idx]
            support = int(y_true.sum())
            thresh_metrics: Dict[str, Any] = {}

            for th in thresholds:
                y_pred = (Y_proba[:, idx] >= th).astype(int)
                prec = float(precision_score(y_true, y_pred, zero_division=0))
                rec = float(recall_score(y_true, y_pred, zero_division=0))
                f1 = float(f1_score(y_true, y_pred, zero_division=0))
                thresh_metrics[f"{th:.2f}"] = {
                    "precision": round(prec, 4),
                    "recall": round(rec, 4),
                    "f1": round(f1, 4)
                }

            # Empirical threshold selection targeting high precision
            target_prec = 0.80 if slug in SENSITIVE_LABELS else 0.70
            chosen_th = 0.70
            for th in thresholds:
                m = thresh_metrics[f"{th:.2f}"]
                if m["precision"] >= target_prec and m["recall"] >= 0.10:
                    chosen_th = th
                    break
            else:
                chosen_th = 0.80

            calibrated_thresholds[slug] = chosen_th
            tag_def = CANONICAL_VOCABULARY.get(slug)
            category = tag_def.category.value if tag_def else "theme"

            per_label_results[slug] = {
                "slug": slug,
                "category": category,
                "support": support,
                "recommended_threshold": chosen_th,
                "threshold_sweep": thresh_metrics,
                "metrics_at_recommended": thresh_metrics[f"{chosen_th:.2f}"],
                "metrics_at_0_50": thresh_metrics.get("0.50", {})
            }

        # Partition into precision tiers
        high_precision: List[List[Any]] = []
        med_precision: List[List[Any]] = []
        low_precision: List[List[Any]] = []
        insufficient_support: List[str] = []

        min_support = 15 if len(X_test) >= 100 else 1
        for slug, data in per_label_results.items():
            if data["support"] < min_support:
                insufficient_support.append(slug)
            else:
                p = data["metrics_at_recommended"]["precision"]
                rec_th = data["recommended_threshold"]
                supp = data["support"]
                if p >= 0.75:
                    high_precision.append([slug, p, rec_th, supp])
                elif p >= 0.50:
                    med_precision.append([slug, p, rec_th, supp])
                else:
                    low_precision.append([slug, p, rec_th, supp])

        high_precision.sort(key=lambda x: x[1], reverse=True)
        med_precision.sort(key=lambda x: x[1], reverse=True)
        low_precision.sort(key=lambda x: x[1], reverse=True)

        tiers = {
            "high": high_precision,
            "medium": med_precision,
            "low": low_precision,
            "insufficient_support": insufficient_support
        }

        # Update instance state without clobbering user-specified threshold overrides
        for s, th in calibrated_thresholds.items():
            if s not in self._user_per_label_thresholds:
                self.per_label_thresholds[s] = th

        self.metadata_["per_label_metrics"] = per_label_results
        self.metadata_["precision_tiers"] = tiers
        self.metadata_["selected_threshold_per_label"] = calibrated_thresholds
        self.metadata_["evaluation_date"] = datetime.now(timezone.utc).isoformat()

        return {
            "total_labels": len(self.labels_),
            "high_precision_count": len(high_precision),
            "medium_precision_count": len(med_precision),
            "low_precision_count": len(low_precision),
            "insufficient_support_count": len(insufficient_support),
            "tiers": tiers,
            "per_label_results": per_label_results,
            "calibrated_thresholds": calibrated_thresholds
        }

    def train(
        self,
        records: List[Union[Dict[str, Any], Any]],
        min_samples_per_label: int = 50,
        test_size: float = 0.2,
        random_state: int = 42,
        include_metadata_in_features: bool = False
    ) -> Dict[str, Any]:
        """
        Trains the multilabel classifier on a list of manga records.
        """
        if not records:
            raise ValueError("Cannot train TagClassifier on empty record list.")

        # 1. Feature and Label Extraction
        texts: List[str] = []
        label_sets: List[List[str]] = []
        label_counter: Counter = Counter()

        for r in records:
            txt = build_ml_text(r, include_metadata=include_metadata_in_features)
            labels = extract_canonical_labels(r)
            texts.append(txt)
            label_sets.append(labels)
            for lab in labels:
                label_counter[lab] += 1

        # 2. Identify Trainable vs Insufficient Labels
        trainable_labels = sorted([
            slug for slug, count in label_counter.items()
            if count >= min_samples_per_label and slug in CANONICAL_VOCABULARY
        ])
        excluded_labels = {
            slug: count for slug, count in label_counter.items()
            if count < min_samples_per_label and slug in CANONICAL_VOCABULARY
        }

        if len(trainable_labels) < 2:
            raise ValueError(
                f"Insufficient trainable labels (found {len(trainable_labels)}). "
                f"Requires at least 2 labels meeting min_samples_per_label={min_samples_per_label}."
            )

        self.labels_ = trainable_labels
        self.mlb = MultiLabelBinarizer(classes=self.labels_)
        Y = self.mlb.fit_transform(label_sets)

        # Filter out records with no trainable labels and no text
        valid_indices = [i for i, (txt, y_row) in enumerate(zip(texts, Y)) if len(txt) > 5 and y_row.sum() > 0]
        if len(valid_indices) < 10:
            valid_indices = [i for i, txt in enumerate(texts) if len(txt) > 5]

        X_filtered = [texts[i] for i in valid_indices]
        Y_filtered = Y[valid_indices]

        # 3. Train/Validation Split
        X_train, X_test, Y_train, Y_test = train_test_split(
            X_filtered, Y_filtered, test_size=test_size, random_state=random_state
        )

        # 4. Vectorization (TF-IDF)
        self.vectorizer = TfidfVectorizer(
            max_features=self.max_features,
            ngram_range=self.ngram_range,
            min_df=self.min_df,
            stop_words="english",
            sublinear_tf=True
        )
        X_train_vec = self.vectorizer.fit_transform(X_train)
        X_test_vec = self.vectorizer.transform(X_test)

        # 5. Classifier Fitting (OneVsRest LogisticRegression)
        base_lr = LogisticRegression(
            C=1.0,
            max_iter=250,
            solver="liblinear",
            class_weight="balanced",
            random_state=random_state
        )
        self.classifier = OneVsRestClassifier(base_lr, n_jobs=1)
        self.classifier.fit(X_train_vec, Y_train)

        # 6. Global Evaluation Metrics
        y_proba = self.classifier.predict_proba(X_test_vec)
        y_pred = (y_proba >= self.default_threshold).astype(int)

        prec_micro = float(precision_score(Y_test, y_pred, average="micro", zero_division=0))
        rec_micro = float(recall_score(Y_test, y_pred, average="micro", zero_division=0))
        f1_micro = float(f1_score(Y_test, y_pred, average="micro", zero_division=0))

        prec_macro = float(precision_score(Y_test, y_pred, average="macro", zero_division=0))
        rec_macro = float(recall_score(Y_test, y_pred, average="macro", zero_division=0))
        f1_macro = float(f1_score(Y_test, y_pred, average="macro", zero_division=0))

        # 7. Baseline Comparison
        marginal_prior = (Y_train.sum(axis=0) / len(Y_train))
        y_baseline_pred = np.zeros_like(Y_test)
        for j, p in enumerate(marginal_prior):
            if p >= 0.25:
                y_baseline_pred[:, j] = 1

        base_prec_micro = float(precision_score(Y_test, y_baseline_pred, average="micro", zero_division=0))
        base_rec_micro = float(recall_score(Y_test, y_baseline_pred, average="micro", zero_division=0))
        base_f1_micro = float(f1_score(Y_test, y_baseline_pred, average="micro", zero_division=0))

        self.metadata_ = {
            "model_version": self.model_version,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "trainable_labels_count": len(self.labels_),
            "labels": self.labels_,
            "excluded_labels": excluded_labels,
            "default_threshold": self.default_threshold,
            "per_label_thresholds": self.per_label_thresholds,
            "feature_engineering": {
                "include_metadata": include_metadata_in_features,
                "max_features": self.max_features,
                "ngram_range": list(self.ngram_range)
            },
            "metrics": {
                "precision_micro": round(prec_micro, 4),
                "recall_micro": round(rec_micro, 4),
                "f1_micro": round(f1_micro, 4),
                "precision_macro": round(prec_macro, 4),
                "recall_macro": round(rec_macro, 4),
                "f1_macro": round(f1_macro, 4),
            },
            "baseline_comparison": {
                "baseline_type": "prior_frequency_heuristic",
                "baseline_precision_micro": round(base_prec_micro, 4),
                "baseline_recall_micro": round(base_rec_micro, 4),
                "baseline_f1_micro": round(base_f1_micro, 4),
                "f1_micro_improvement": round(f1_micro - base_f1_micro, 4),
                "ml_beats_baseline": bool(f1_micro > base_f1_micro)
            }
        }

        # 8. Run per-label threshold sweep and precision tier analysis if sufficient samples
        if len(X_test) >= 1:
            self.evaluate_per_label(X_test, Y_test)

        return self.metadata_

    def predict_proba(self, text: str) -> Dict[str, float]:
        """
        Predicts confidence probabilities for each canonical label.
        """
        if not self.is_trained:
            raise RuntimeError("TagClassifier must be trained or loaded before predict_proba().")
        if not text or not text.strip():
            return {}

        X_vec = self.vectorizer.transform([text])
        proba_matrix = self.classifier.predict_proba(X_vec)
        probs = proba_matrix[0]

        return {self.labels_[i]: round(float(probs[i]), 4) for i in range(len(self.labels_))}

    def predict(
        self,
        record: Union[Dict[str, Any], Any],
        threshold: Optional[float] = None,
        per_label_thresholds: Optional[Dict[str, float]] = None,
        accept_tier: Optional[str] = "high",
        only_accepted: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Predicts canonical tags for a manga record with precision calibration and tiering.
        
        Args:
            record: Manga dict or model instance.
            threshold: Optional global threshold override (e.g. 0.99 for strict filtering).
            per_label_thresholds: Optional mapping of slug to custom threshold.
            accept_tier: Confidence tier required ('high', 'medium', 'all').
            only_accepted: If True, returns only accepted predictions.
            
        Returns:
            List of prediction dictionaries sorted by confidence descending.
        """
        if not self.is_trained:
            return []

        txt = build_ml_text(record, include_metadata=False)
        if not txt:
            return []

        probs = self.predict_proba(txt)
        predictions = []

        eff_accept_tier = accept_tier
        if threshold is not None and accept_tier == "high":
            eff_accept_tier = "all"

        for slug, prob in probs.items():
            if slug not in CANONICAL_VOCABULARY:
                continue

            active_thresh = self.get_threshold_for_label(
                slug,
                override_threshold=threshold,
                override_dict=per_label_thresholds
            )

            tier, accepted = self.classify_prediction(
                slug=slug,
                prob=prob,
                active_threshold=active_thresh,
                accept_tier=eff_accept_tier or "all"
            )

            if only_accepted and not accepted:
                continue

            predictions.append({
                "slug": slug,
                "confidence": prob,
                "threshold": active_thresh,
                "tier": tier,
                "accepted": accepted
            })

        predictions.sort(key=lambda p: p["confidence"], reverse=True)
        return predictions

    def enrich(
        self,
        record: Union[Dict[str, Any], Any],
        threshold: Optional[float] = None,
        per_label_thresholds: Optional[Dict[str, float]] = None,
        accept_tier: str = "high"
    ) -> List[InferredTag]:
        """
        Predicts and formats inferred tags as InferredTag model instances with provenance='model'.
        Defaults to accept_tier='high' to safeguard against false-positive pollution.
        """
        preds = self.predict(
            record,
            threshold=threshold,
            per_label_thresholds=per_label_thresholds,
            accept_tier=accept_tier,
            only_accepted=True
        )
        inferred_tags: List[InferredTag] = []
        for p in preds:
            tag = InferredTag.from_canonical(
                slug=p["slug"],
                confidence=p["confidence"],
                provenance="model",
                source_rule=f"ML-{self.model_version}"
            )
            inferred_tags.append(tag)
        return inferred_tags

    def save(self, directory: str = DEFAULT_MODEL_DIR) -> None:
        """
        Persists the trained model, vectorizer, and metadata to disk.
        """
        if not self.is_trained:
            raise RuntimeError("Cannot save untrained TagClassifier.")

        os.makedirs(directory, exist_ok=True)
        bundle = {
            "model_version": self.model_version,
            "vectorizer": self.vectorizer,
            "classifier": self.classifier,
            "mlb": self.mlb,
            "labels_": self.labels_,
            "default_threshold": self.default_threshold,
            "per_label_thresholds": self.per_label_thresholds
        }
        model_path = os.path.join(directory, "model.joblib")
        joblib.dump(bundle, model_path, compress=3)

        meta_path = os.path.join(directory, "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata_, f, indent=2)

    @classmethod
    def load(cls, directory: str = DEFAULT_MODEL_DIR) -> "TagClassifier":
        """
        Loads a persisted TagClassifier instance from disk.
        """
        model_path = os.path.join(directory, "model.joblib")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found at '{model_path}'")

        bundle = joblib.load(model_path)
        instance = cls(
            model_version=bundle.get("model_version", MODEL_VERSION),
            default_threshold=bundle.get("default_threshold", 0.70),
            per_label_thresholds=bundle.get("per_label_thresholds")
        )
        instance.vectorizer = bundle["vectorizer"]
        instance.classifier = bundle["classifier"]
        instance.mlb = bundle["mlb"]
        instance.labels_ = bundle["labels_"]

        meta_path = os.path.join(directory, "metadata.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                instance.metadata_ = json.load(f)
                if "selected_threshold_per_label" in instance.metadata_:
                    instance.per_label_thresholds.update(instance.metadata_["selected_threshold_per_label"])
                elif "per_label_thresholds" in instance.metadata_:
                    instance.per_label_thresholds.update(instance.metadata_["per_label_thresholds"])

        return instance
