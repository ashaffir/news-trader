from django import forms
from .models import TradingConfig, AlertSettings


class TrackedCompanyImportForm(forms.Form):
    csv_file = forms.FileField(allow_empty_file=False, label="CSV file")
    deactivate_missing = forms.BooleanField(
        required=False, initial=False, label="Deactivate companies missing from CSV"
    )

    def clean_csv_file(self):
        f = self.cleaned_data["csv_file"]
        if not getattr(f, "size", 0):
            raise forms.ValidationError("Uploaded file is empty.")
        return f


class _ConfigFormMixin:
    """Apply consistent small, clean styling to all config forms."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            existing = widget.attrs.get("class", "")

            # Common sizing
            if isinstance(widget, forms.NumberInput):
                widget.attrs.setdefault("class", (existing + " form-control form-control-sm").strip())
                widget.attrs.setdefault("step", "0.01")
                widget.attrs.setdefault("style", "max-width: 140px;")
            elif isinstance(widget, forms.TextInput):
                widget.attrs.setdefault("class", (existing + " form-control form-control-sm").strip())
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", (existing + " form-control").strip())
                widget.attrs.setdefault("rows", 8)
                widget.attrs.setdefault("style", "font-family: ui-monospace, SFMono-Regular, Menlo, monospace;")
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", (existing + " form-select form-select-sm w-auto").strip())
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", (existing + " form-check-input").strip())


class TradingBasicsForm(_ConfigFormMixin, forms.ModelForm):
    class Meta:
        model = TradingConfig
        fields = [
            "bot_enabled",
            "autostart",
            "trading_enabled",
            "market_hours_only",
            "intraday_trading",
            "intraday_close_minutes_before",
            "is_active",
            "name",
        ]


class PositionSizingForm(_ConfigFormMixin, forms.ModelForm):
    class Meta:
        model = TradingConfig
        fields = [
            "position_sizing_method",
            "default_position_size",
            "max_position_size",
        ]


class RiskLimitsForm(_ConfigFormMixin, forms.ModelForm):
    class Meta:
        model = TradingConfig
        fields = [
            "stop_loss_percentage",
            "take_profit_percentage",
            "max_daily_trades",
            "max_concurrent_open_trades",
            "max_total_open_exposure",
        ]


class EntryFreshnessForm(_ConfigFormMixin, forms.ModelForm):
    class Meta:
        model = TradingConfig
        fields = [
            "min_confidence_threshold",
            "enter_confirmation_enabled",
            "enter_confirm_window_minutes",
            "enter_price_change_threshold_pct",
            "enter_volume_ma_window",
            "enter_volume_multiplier_threshold",
            "freshness_decay_constant_min",
            "freshness_threshold",
        ]


class LlmHoldForm(_ConfigFormMixin, forms.ModelForm):
    class Meta:
        model = TradingConfig
        fields = [
            "llm_model",
            "llm_prompt_template",
            "confidence_weight_impact_size",
            "confidence_weight_time_proximity",
            "confidence_weight_clarity",
            "confidence_weight_volatility_sensitivity",
            "confidence_weight_duration",
            "hold_time_time_to_peak_min_hours",
            "hold_time_time_to_peak_max_hours",
            "hold_time_time_proximity_exponent",
            "hold_time_tail_multiplier",
            "hold_time_tail_duration_exponent",
            "hold_time_tail_impact_base",
            "hold_time_tail_impact_scale",
            "hold_time_min_hours",
        ]
        widgets = {
            "llm_prompt_template": forms.Textarea(attrs={"rows": 12, "style": "font-family: ui-monospace, SFMono-Regular, Menlo, monospace;"}),
        }


class ExitProtectForm(_ConfigFormMixin, forms.ModelForm):
    class Meta:
        model = TradingConfig
        fields = [
            "dynamic_exit_drawdown_tolerance_pct",
            "dynamic_exit_window_minutes",
            "profit_protect_threshold_pct",
            "profit_protect_trailing_distance_pct",
            "profit_protect_window_minutes",
        ]


class OvernightForm(_ConfigFormMixin, forms.ModelForm):
    class Meta:
        model = TradingConfig
        fields = [
            "overnight_enabled",
            "overnight_reduce_sl_factor",
            "overnight_max_age_hours",
        ]

class AlertSettingsForm(forms.ModelForm):
    class Meta:
        model = AlertSettings
        fields = [
            "enabled",
            "bot_status_enabled",
            "order_open_enabled",
            "order_close_enabled",
            "trading_limit_enabled",
            "system_errors_enabled",
            "heartbeat_enabled",
            "heartbeat_interval_minutes",
        ]

