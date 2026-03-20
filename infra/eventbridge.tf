# ── Nightly data collection (00:05 UTC = 01:05 CET / 02:05 CEST) ────────────
# By this time, yesterday's generation + balancing data is fully settled.
# Fetches generation, balancing, load forecast, weather forecast, gas prices.
resource "aws_cloudwatch_event_rule" "midnight_collect" {
  name                = "${var.project}-midnight-collect"
  description         = "Nightly data collection at 00:05 UTC (01:05 CET)"
  schedule_expression = "cron(5 0 * * ? *)"
}

resource "aws_cloudwatch_event_target" "midnight_collect_lambda" {
  rule      = aws_cloudwatch_event_rule.midnight_collect.name
  target_id = "${var.project}-midnight-collect"
  arn       = aws_lambda_function.scheduler.arn
  input     = jsonencode({ midnight_collect = true })
}

# ── Nightly ML predictions (00:20 UTC = 01:20 CET / 02:20 CEST) ─────────────
# Runs 15 min after data collection to ensure fresh data is available.
# Records same_weekday_avg + LightGBM predictions for tomorrow.
resource "aws_cloudwatch_event_rule" "midnight_predict" {
  name                = "${var.project}-midnight-predict"
  description         = "ML predictions at 00:20 UTC (after data collection)"
  schedule_expression = "cron(20 0 * * ? *)"
}

resource "aws_cloudwatch_event_target" "midnight_predict_lambda" {
  rule      = aws_cloudwatch_event_rule.midnight_predict.name
  target_id = "${var.project}-midnight-predict"
  arn       = aws_lambda_function.scheduler.arn
  input     = jsonencode({ predict_only = true })
}

# ── Nightly retry: data collection (04:05 UTC = 05:05 CET / 06:05 CEST) ─────
# Idempotent — cached data is skipped, so a no-op if 00:05 succeeded.
resource "aws_cloudwatch_event_rule" "retry_collect" {
  name                = "${var.project}-retry-collect"
  description         = "Retry data collection at 04:05 UTC if midnight run failed"
  schedule_expression = "cron(5 4 * * ? *)"
}

resource "aws_cloudwatch_event_target" "retry_collect_lambda" {
  rule      = aws_cloudwatch_event_rule.retry_collect.name
  target_id = "${var.project}-retry-collect"
  arn       = aws_lambda_function.scheduler.arn
  input     = jsonencode({ midnight_collect = true })
}

# ── Nightly retry: predictions (04:20 UTC = 05:20 CET / 06:20 CEST) ─────────
# Idempotent — predictions upsert, so a no-op if 00:20 succeeded.
resource "aws_cloudwatch_event_rule" "retry_predict" {
  name                = "${var.project}-retry-predict"
  description         = "Retry predictions at 04:20 UTC if midnight run failed"
  schedule_expression = "cron(20 4 * * ? *)"
}

resource "aws_cloudwatch_event_target" "retry_predict_lambda" {
  rule      = aws_cloudwatch_event_rule.retry_predict.name
  target_id = "${var.project}-retry-predict"
  arn       = aws_lambda_function.scheduler.arn
  input     = jsonencode({ predict_only = true })
}

# ── Daily price fetch (12:30 UTC = 13:30 CET / 14:30 CEST) ──────────────────
# ENTSO-E publishes next-day prices at ~13:00 CET.
resource "aws_cloudwatch_event_rule" "daily_fetch" {
  name                = "${var.project}-daily-fetch"
  description         = "Fetch ENTSO-E spot prices daily at 12:30 UTC (13:30 CET)"
  schedule_expression = "cron(30 12 * * ? *)"
}

resource "aws_cloudwatch_event_target" "scheduler_lambda" {
  rule      = aws_cloudwatch_event_rule.daily_fetch.name
  target_id = "${var.project}-scheduler"
  arn       = aws_lambda_function.scheduler.arn
}
