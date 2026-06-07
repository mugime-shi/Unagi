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
      API_KEY            = var.api_key
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
  memory_size   = 512  # LightGBM training needs >256 MB
  timeout       = 600  # data collection + ML training can take several minutes

  environment {
    variables = {
      DATABASE_URL        = var.database_url
      ENTSOE_API_KEY      = var.entsoe_api_key
      DEBUG               = "false"
      VAPID_PRIVATE_KEY   = var.vapid_private_key
      VAPID_PUBLIC_KEY    = var.vapid_public_key
      VAPID_CONTACT       = var.vapid_contact
      TELEGRAM_BOT_TOKEN  = var.telegram_bot_token
      TELEGRAM_CHAT_ID    = var.telegram_chat_id
      # M ensemble (regime-specific soft blend). Validated 2026-04-25 on a
      # 90-day backtest: overall MAE -2.5%, calm -1.8%, volatile -2.9% with
      # the dead-zone gate [0.4, 0.6) hard-coded as the default.
      #
      # DISABLED 2026-06-06: on a cold model cache the 3-model retrain
      # (A 500d + B 500d + classifier) exceeded the 512 MB / 600 s limits,
      # timing out. Default async retries (x2) then re-read the full 500-day
      # training windows from Supabase, blowing past the 5.5 GB/mo egress
      # free-tier quota. Reverted to Model A only. Re-enable only after
      # bumping memory and capping retries (see work/HANDOVER).
      LGBM_USE_ENSEMBLE   = "0"
      # Model A only needs a 365-day window. The 500-day window was added for
      # the (now-disabled) volatile specialist; reverting cuts the cold-retrain
      # read volume and Supabase egress. (2026-06-06)
      LGBM_TRAIN_DAYS     = "365"
    }
  }

  lifecycle {
    ignore_changes = [image_uri]
  }
}

# Cap async-invocation retries to 0. EventBridge invokes the scheduler
# asynchronously, and the AWS default of 2 retries meant a single cold-cache
# timeout re-read the full training window from Supabase up to 3x — the main
# driver of the 2026-06 egress-quota blowout. One attempt per trigger is enough;
# the next scheduled run recovers any genuinely missed fetch. (2026-06-06)
resource "aws_lambda_function_event_invoke_config" "scheduler" {
  function_name          = aws_lambda_function.scheduler.function_name
  maximum_retry_attempts = 0
}

# Allow EventBridge to invoke the Scheduler Lambda (afternoon price fetch)
resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_fetch.arn
}

# Allow EventBridge to invoke the Scheduler Lambda (nightly data collection)
resource "aws_lambda_permission" "eventbridge_midnight_collect" {
  statement_id  = "AllowEventBridgeMidnightCollect"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.midnight_collect.arn
}

# Allow EventBridge to invoke the Scheduler Lambda (nightly prediction)
resource "aws_lambda_permission" "eventbridge_midnight_predict" {
  statement_id  = "AllowEventBridgeMidnightPredict"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.midnight_predict.arn
}

# Allow EventBridge to invoke the Scheduler Lambda (retry data collection)
resource "aws_lambda_permission" "eventbridge_retry_collect" {
  statement_id  = "AllowEventBridgeRetryCollect"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.retry_collect.arn
}

# Allow EventBridge to invoke the Scheduler Lambda (retry prediction)
resource "aws_lambda_permission" "eventbridge_retry_predict" {
  statement_id  = "AllowEventBridgeRetryPredict"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.retry_predict.arn
}

# Allow EventBridge to invoke the Scheduler Lambda (price retry)
resource "aws_lambda_permission" "eventbridge_price_retry" {
  for_each      = aws_cloudwatch_event_rule.price_retry
  statement_id  = "AllowEventBridgePriceRetry-${replace(each.key, " ", "")}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = each.value.arn
}

resource "aws_lambda_permission" "eventbridge_hourly_generation" {
  statement_id  = "AllowEventBridgeHourlyGeneration"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.hourly_generation.arn
}

resource "aws_lambda_permission" "eventbridge_weekly_backfill" {
  statement_id  = "AllowEventBridgeWeeklyBackfill"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.weekly_backfill.arn
}
