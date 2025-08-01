# Generated migration for enhanced position management features

from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_trade_stop_loss_price_percentage_and_more'),
    ]

    operations = [
        # Add new TradingConfig fields for position management
        migrations.AddField(
            model_name='tradingconfig',
            name='max_position_hold_time_hours',
            field=models.IntegerField(
                default=24,
                help_text='Maximum hours to hold a position before automatic close',
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(168)]
            ),
        ),
        migrations.AddField(
            model_name='tradingconfig',
            name='min_confidence_for_adjustment',
            field=models.FloatField(
                default=0.8,
                help_text='Minimum confidence required to adjust existing position TP/SL',
                validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(1.0)]
            ),
        ),
        migrations.AddField(
            model_name='tradingconfig',
            name='conservative_adjustment_factor',
            field=models.FloatField(
                default=0.5,
                help_text='Conservative factor for TP/SL adjustments (0.5 = 50% of full adjustment)',
                validators=[django.core.validators.MinValueValidator(0.1), django.core.validators.MaxValueValidator(1.0)]
            ),
        ),
        migrations.AddField(
            model_name='tradingconfig',
            name='allow_position_adjustments',
            field=models.BooleanField(
                default=True,
                help_text='Allow one-time TP/SL adjustments based on new supporting analysis'
            ),
        ),
        migrations.AddField(
            model_name='tradingconfig',
            name='monitoring_frequency_minutes',
            field=models.IntegerField(
                default=1,
                help_text='How often to monitor positions for TP/SL triggers (in minutes)',
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(60)]
            ),
        ),
        
        # Add new Trade fields for position adjustment tracking
        migrations.AddField(
            model_name='trade',
            name='has_been_adjusted',
            field=models.BooleanField(
                default=False,
                help_text='Whether TP/SL has been adjusted (one-time only)'
            ),
        ),
        migrations.AddField(
            model_name='trade',
            name='original_stop_loss_price',
            field=models.FloatField(
                blank=True,
                null=True,
                help_text='Original stop loss price before any adjustments'
            ),
        ),
        migrations.AddField(
            model_name='trade',
            name='original_take_profit_price',
            field=models.FloatField(
                blank=True,
                null=True,
                help_text='Original take profit price before any adjustments'
            ),
        ),
        
        # Update Trade model close reason choices
        migrations.AlterField(
            model_name='trade',
            name='close_reason',
            field=models.CharField(
                blank=True,
                choices=[
                    ('manual', 'Manual Close'),
                    ('stop_loss', 'Stop Loss'),
                    ('take_profit', 'Take Profit'),
                    ('time_limit', 'Time Limit'),
                    ('market_close', 'Market Close'),
                    ('market_consensus_lost', 'Market Consensus Lost'),
                ],
                max_length=25,  # Increased to accommodate new choice
                null=True
            ),
        ),
    ] 