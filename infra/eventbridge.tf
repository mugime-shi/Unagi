# Nightly prediction cron — complete yesterday's data, then record ML predictions.
# 00:05 UTC = 01:05 CET (winter) / 02:05 CEST (summer).
# By this time, yesterday's generation + balancing data is fully settled.
resource "aws_cloudwatch_event_rule" "midnight_predict" {
  name                = "${var.project}-midnight-predict"
  description         = "Complete yesterday data + ML predictions at 00:05 UTC (01:05 CET)"
  schedule_expression = "cron(5 0 * * ? *)"
}

resource "aws_cloudwatch_event_target" "midnight_predict_lambda" {
  rule      = aws_cloudwatch_event_rule.midnight_predict.name
  target_id = "${var.project}-midnight-predict"
  arn       = aws_lambda_function.scheduler.arn
  input     = jsonencode({ midnight_predict = true })
}

# ENTSO-E publishes next-day prices at ~13:00 CET.
# 12:30 UTC = 13:30 CET (winter) / 14:30 CEST (summer) — always after publication.
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
