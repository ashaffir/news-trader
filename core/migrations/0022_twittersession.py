from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_add_unique_active_trade_constraint'),
    ]

    operations = [
        migrations.CreateModel(
            name='TwitterSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('username', models.CharField(max_length=150, unique=True)),
                ('email', models.EmailField(blank=True, max_length=254, null=True)),
                ('password', models.CharField(blank=True, max_length=255, null=True)),
                ('storage_state', models.JSONField(blank=True, null=True)),
                ('cookies', models.JSONField(blank=True, null=True)),
                ('last_login_at', models.DateTimeField(blank=True, null=True)),
                (
                    'status',
                    models.CharField(
                        choices=[('ok', 'OK'), ('pending', 'Pending'), ('error', 'Error')],
                        default='ok',
                        max_length=20,
                    ),
                ),
                ('last_error', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
    ]


