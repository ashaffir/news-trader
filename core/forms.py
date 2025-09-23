from django import forms


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


