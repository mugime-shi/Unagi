# ---------------------------------------------------------------------------
# monitoring.tf — CloudWatch Alarms + SNS + Telegram forwarder Lambda
#
# Flow: CloudWatch Alarm → SNS topic → alarm_handler Lambda → Telegram
#
# Why SNS as the middle layer?
#   SNS decouples the alarm from the delivery mechanism. If we later add
#   email, PagerDuty, or Slack, we just add another SNS subscription without
#   touching the alarm definitions.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Alarm handler Lambda — packaged as a zip (stdlib only, no Docker)
# ---------------------------------------------------------------------------

# Build a zip from the single-file handler at deploy time
data "archive_file" "alarm_handler_zip" {
  type        = "zip"
  source_file = "${path.module}/../backend/alarm_handler.py"
  output_path = "${path.module}/alarm_handler.zip"  # gitignored build artifact
}

resource "aws_iam_role" "alarm_handler" {
  name = "${var.project}-alarm-handler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "alarm_handler_basic" {
  role       = aws_iam_role.alarm_handler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "alarm_handler" {
  function_name = "${var.project}-alarm-handler"
  role          = aws_iam_role.alarm_handler.arn

  # zip runtime — no Docker image needed for a stdlib-only helper
  runtime          = "python3.12"
  handler          = "alarm_handler.handler"
  filename         = data.archive_file.alarm_handler_zip.output_path
  source_code_hash = data.archive_file.alarm_handler_zip.output_base64sha256

  timeout = 15

  environment {
    variables = {
      TELEGRAM_BOT_TOKEN = var.telegram_bot_token
      TELEGRAM_CHAT_ID   = var.telegram_chat_id
    }
  }
}

# ---------------------------------------------------------------------------
# SNS topic + subscription
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

resource "aws_sns_topic_subscription" "alarm_handler" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.alarm_handler.arn
}

# Allow SNS to invoke the alarm handler Lambda
resource "aws_lambda_permission" "sns_invoke_alarm_handler" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alarm_handler.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.alerts.arn
}

# ---------------------------------------------------------------------------
# CloudWatch Alarms
# ---------------------------------------------------------------------------

# Scheduler Lambda: any error is critical — means no price fetch today
resource "aws_cloudwatch_metric_alarm" "scheduler_errors" {
  alarm_name          = "${var.project}-scheduler-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300 # 5-minute window matches EventBridge trigger frequency
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Namazu scheduler Lambda failed — today's price fetch may have been skipped"
  treat_missing_data  = "notBreaching" # silence when Lambda hasn't run yet (weekends etc.)
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    FunctionName = aws_lambda_function.scheduler.function_name
  }
}

# API Lambda: sustained errors (15 min) before alerting — tolerate cold-start blips
resource "aws_cloudwatch_metric_alarm" "api_errors" {
  alarm_name          = "${var.project}-api-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3    # 3 × 5-min periods = 15 min sustained before alerting
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5    # occasional errors are fine; alert on sustained failure
  alarm_description   = "Namazu API Lambda error rate elevated for 15 minutes"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    FunctionName = aws_lambda_function.api.function_name
  }
}
