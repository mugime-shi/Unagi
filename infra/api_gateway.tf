resource "aws_apigatewayv2_api" "main" {
  name          = "${var.project}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["https://unagieel.net", "https://namazu-el.vercel.app", "http://localhost:5173", "http://localhost:3000"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["Content-Type", "X-Unagi-Key"]
    max_age       = 300
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  # Rate limiting at the HTTP API stage level.
  # HTTP API v2 uses stage-level throttling instead of REST API's Usage Plans.
  # burst_limit: max concurrent requests in a single burst (token bucket capacity)
  # rate_limit:  steady-state requests per second (token refill rate)
  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 30
  }

  # Per-path request counts (the Lambda does not log paths). Source IP and
  # user agent are deliberately left out; requests arrive via the Vercel
  # rewrite proxy anyway, so the IP would be Vercel's.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      time    = "$context.requestTime"
      method  = "$context.httpMethod"
      path    = "$context.path"
      status  = "$context.status"
      latency = "$context.responseLatency"
    })
  }
}

resource "aws_cloudwatch_log_group" "api_access" {
  name = "/aws/apigateway/${var.project}-api-access"
  # ~10 MB/year at current traffic, so keeping two years (year-over-year
  # comparison across winter price spikes) costs effectively nothing.
  retention_in_days = 731
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

# Catch-all route: forward everything to FastAPI
resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# Root route (for /health etc.)
resource "aws_apigatewayv2_route" "root" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "ANY /"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}
