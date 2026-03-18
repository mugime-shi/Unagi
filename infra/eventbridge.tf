# Morning prediction cron — record ML forecasts BEFORE day-ahead publication (~13:00 CET).
# 05:00 UTC = 06:00 CET (winter) / 07:00 CEST (summer).
resource "aws_cloudwatch_event_rule" "morning_predict" {
  name                = "${var.project}-morning-predict"
  description         = "Record ML price predictions at 05:00 UTC (06:00 CET) before day-ahead publication"
  schedule_expression = "cron(0 5 * * ? *)"
}

resource "aws_cloudwatch_event_target" "morning_predict_lambda" {
  rule      = aws_cloudwatch_event_rule.morning_predict.name
  target_id = "${var.project}-morning-predict"
  arn       = aws_lambda_function.scheduler.arn
  input     = jsonencode({ predict_only = true })
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
