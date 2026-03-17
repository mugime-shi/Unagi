# ── API Lambda (Mangum wraps FastAPI for Lambda invocation) ──────────────────
resource "aws_lambda_function" "api" {
  function_name = "${var.project}-api"
  role          = aws_iam_role.lambda_exec.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
  architectures = ["arm64"]
  memory_size   = 512
  timeout       = 30

  environment {
    variables = {
      DATABASE_URL      = var.database_url
      ENTSOE_API_KEY    = var.entsoe_api_key
      DEBUG             = "false"
      VAPID_PRIVATE_KEY = var.vapid_private_key
      VAPID_PUBLIC_KEY  = var.vapid_public_key
      VAPID_CONTACT     = var.vapid_contact
      TELEGRAM_BOT_TOKEN = var.telegram_bot_token
      TELEGRAM_CHAT_ID   = var.telegram_chat_id
    }
  }

  # image_uri is managed by CI/CD (docker push), not by Terraform
  lifecycle {
    ignore_changes = [image_uri]
  }
}

# Allow API Gateway to invoke the API Lambda
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

# ── Scheduler Lambda (EventBridge → fetch_prices.lambda_handler) ──────────────
resource "aws_lambda_function" "scheduler" {
  function_name = "${var.project}-scheduler"
  role          = aws_iam_role.lambda_exec.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.scheduler.repository_url}:${var.image_tag}"
  architectures = ["arm64"]
  memory_size   = 256
  timeout       = 300 # backfill can take a few minutes

  environment {
    variables = {
      DATABASE_URL       = var.database_url
      ENTSOE_API_KEY     = var.entsoe_api_key
      DEBUG              = "false"
      VAPID_PRIVATE_KEY  = var.vapid_private_key
      VAPID_PUBLIC_KEY   = var.vapid_public_key
      VAPID_CONTACT      = var.vapid_contact
      TELEGRAM_BOT_TOKEN = var.telegram_bot_token
      TELEGRAM_CHAT_ID   = var.telegram_chat_id
    }
  }

  lifecycle {
    ignore_changes = [image_uri]
  }
}

# Allow EventBridge to invoke the Scheduler Lambda
resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_fetch.arn
}
