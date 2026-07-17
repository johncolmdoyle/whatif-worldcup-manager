#!/usr/bin/env bash

set -euo pipefail

PROFILE="${AWS_PROFILE:-johndoyle}"
AWS_REGION="${AWS_REGION:-eu-west-1}"
CERT_REGION="${CERT_REGION:-us-east-1}"
ROOT_DOMAIN="${ROOT_DOMAIN:-johndoyle.ie}"
FRONTEND_DOMAIN="${FRONTEND_DOMAIN:-whatifworldcup.${ROOT_DOMAIN}}"
API_DOMAIN="${API_DOMAIN:-api.whatifworldcup.${ROOT_DOMAIN}}"
APP_NAME="${APP_NAME:-whatif-worldcup-manager}"
FRONTEND_BUCKET="${FRONTEND_BUCKET:-${APP_NAME//_/-}-frontend-${ROOT_DOMAIN//./-}}"
ECR_REPO="${ECR_REPO:-${APP_NAME}-backend}"
APP_RUNNER_SERVICE_NAME="${APP_RUNNER_SERVICE_NAME:-${APP_NAME}-backend}"
APP_RUNNER_ROLE_NAME="${APP_RUNNER_ROLE_NAME:-AppRunnerECRAccessRole}"
APP_RUNNER_AUTOSCALING_NAME="${APP_RUNNER_AUTOSCALING_NAME:-wwcm-single-instance}"
FRONTEND_DIR="${FRONTEND_DIR:-frontend}"
BACKEND_DIR="${BACKEND_DIR:-backend}"
FRONTEND_CERT_TAG_VALUE="${FRONTEND_CERT_TAG_VALUE:-${APP_NAME}-frontend}"

export AWS_PAGER=""

log() {
  printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

aws_profile() {
  aws --profile "$PROFILE" "$@"
}

aws_region() {
  local region="$1"
  shift
  aws --profile "$PROFILE" --region "$region" "$@"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

json_escape() {
  python3 - <<'PY' "$1"
import json
import sys
print(json.dumps(sys.argv[1]))
PY
}

upsert_record_file() {
  local hosted_zone_id="$1"
  local record_name="$2"
  local record_type="$3"
  local record_value="$4"
  local record_json

  record_json="$(mktemp)"
  cat >"$record_json" <<JSON
{
  "Comment": "Managed by ${APP_NAME} deploy script",
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": ${record_name},
        "Type": "${record_type}",
        "TTL": 300,
        "ResourceRecords": [
          {
            "Value": ${record_value}
          }
        ]
      }
    }
  ]
}
JSON

  aws_profile route53 change-resource-record-sets \
    --hosted-zone-id "$hosted_zone_id" \
    --change-batch "file://${record_json}" >/dev/null
  rm -f "$record_json"
}

upsert_alias_record() {
  local hosted_zone_id="$1"
  local record_name="$2"
  local alias_name="$3"
  local alias_zone_id="$4"
  local alias_json

  alias_json="$(mktemp)"
  cat >"$alias_json" <<JSON
{
  "Comment": "Managed by ${APP_NAME} deploy script",
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": ${record_name},
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "${alias_zone_id}",
          "DNSName": ${alias_name},
          "EvaluateTargetHealth": false
        }
      }
    }
  ]
}
JSON

  aws_profile route53 change-resource-record-sets \
    --hosted-zone-id "$hosted_zone_id" \
    --change-batch "file://${alias_json}" >/dev/null
  rm -f "$alias_json"
}

wait_for_frontend_certificate() {
  local certificate_arn="$1"
  local status=""

  while true; do
    status="$(aws_region "$CERT_REGION" acm describe-certificate \
      --certificate-arn "$certificate_arn" \
      --query 'Certificate.Status' \
      --output text)"

    if [[ "$status" == "ISSUED" ]]; then
      break
    fi

    log "Waiting for ACM certificate ${certificate_arn} in ${CERT_REGION} to be issued. Current status: ${status}"
    sleep 15
  done
}

wait_for_app_runner_service() {
  local service_arn="$1"
  local status=""

  while true; do
    status="$(aws_region "$AWS_REGION" apprunner describe-service \
      --service-arn "$service_arn" \
      --query 'Service.Status' \
      --output text)"

    if [[ "$status" == "RUNNING" ]]; then
      break
    fi

    if [[ "$status" == "CREATE_FAILED" || "$status" == "DELETE_FAILED" || "$status" == "PAUSED" || "$status" == "OPERATION_FAILED" ]]; then
      echo "App Runner service entered an unexpected state: ${status}" >&2
      exit 1
    fi

    log "Waiting for App Runner service ${service_arn} in ${AWS_REGION}. Current status: ${status}"
    sleep 20
  done
}

wait_for_app_runner_service_deletion() {
  local service_arn="$1"
  local status=""

  while true; do
    if ! aws_region "$AWS_REGION" apprunner describe-service --service-arn "$service_arn" >/dev/null 2>&1; then
      break
    fi

    status="$(
      aws_region "$AWS_REGION" apprunner describe-service \
        --service-arn "$service_arn" \
        --query 'Service.Status' \
        --output text
    )"

    if [[ "$status" == "DELETED" ]]; then
      break
    fi

    log "Waiting for failed App Runner service ${service_arn} to be deleted"
    sleep 10
  done
}

wait_for_distribution() {
  local distribution_id="$1"
  local status=""

  while true; do
    status="$(aws_profile cloudfront get-distribution \
      --id "$distribution_id" \
      --query 'Distribution.Status' \
      --output text)"

    if [[ "$status" == "Deployed" ]]; then
      break
    fi

    log "Waiting for CloudFront distribution ${distribution_id}. Current status: ${status}"
    sleep 30
  done
}

ensure_bucket() {
  if aws_region "$AWS_REGION" s3api head-bucket --bucket "$FRONTEND_BUCKET" >/dev/null 2>&1; then
    log "S3 bucket ${FRONTEND_BUCKET} already exists"
  else
    log "Creating S3 bucket ${FRONTEND_BUCKET} in ${AWS_REGION}"
    aws_region "$AWS_REGION" s3api create-bucket \
      --bucket "$FRONTEND_BUCKET" \
      --create-bucket-configuration "LocationConstraint=${AWS_REGION}" >/dev/null
  fi

  aws_region "$AWS_REGION" s3 website "s3://${FRONTEND_BUCKET}" \
    --index-document index.html \
    --error-document index.html >/dev/null

  aws_region "$AWS_REGION" s3api put-public-access-block \
    --bucket "$FRONTEND_BUCKET" \
    --public-access-block-configuration \
      BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false >/dev/null

  local bucket_policy
  bucket_policy="$(mktemp)"
  cat >"$bucket_policy" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::${FRONTEND_BUCKET}/*"
    }
  ]
}
JSON
  aws_region "$AWS_REGION" s3api put-bucket-policy \
    --bucket "$FRONTEND_BUCKET" \
    --policy "file://${bucket_policy}" >/dev/null
  rm -f "$bucket_policy"
}

ensure_frontend_certificate() {
  local existing_cert
  existing_cert="$(
    aws_region "$CERT_REGION" acm list-certificates \
      --certificate-statuses ISSUED PENDING_VALIDATION INACTIVE EXPIRED VALIDATION_TIMED_OUT REVOKED FAILED \
      --query "CertificateSummaryList[?DomainName=='${FRONTEND_DOMAIN}'] | [0].CertificateArn" \
      --output text
  )"

  if [[ -z "$existing_cert" || "$existing_cert" == "None" ]]; then
    log "Requesting ACM certificate for ${FRONTEND_DOMAIN} in ${CERT_REGION}"
    existing_cert="$(
      aws_region "$CERT_REGION" acm request-certificate \
        --domain-name "$FRONTEND_DOMAIN" \
        --validation-method DNS \
        --tags "Key=Project,Value=${FRONTEND_CERT_TAG_VALUE}" \
        --query 'CertificateArn' \
        --output text
    )"
  else
    log "Reusing ACM certificate ${existing_cert} for ${FRONTEND_DOMAIN}"
  fi

  local validation_name validation_value
  validation_name="$(
    aws_region "$CERT_REGION" acm describe-certificate \
      --certificate-arn "$existing_cert" \
      --query 'Certificate.DomainValidationOptions[0].ResourceRecord.Name' \
      --output text
  )"
  validation_value="$(
    aws_region "$CERT_REGION" acm describe-certificate \
      --certificate-arn "$existing_cert" \
      --query 'Certificate.DomainValidationOptions[0].ResourceRecord.Value' \
      --output text
  )"

  if [[ "$validation_name" != "None" && "$validation_value" != "None" ]]; then
    upsert_record_file \
      "$HOSTED_ZONE_ID" \
      "$(json_escape "${validation_name}")" \
      "CNAME" \
      "$(json_escape "${validation_value}")"
  fi

  wait_for_frontend_certificate "$existing_cert"
  FRONTEND_CERT_ARN="$existing_cert"
}

ensure_cloudfront_distribution() {
  local bucket_website_domain distribution_id existing_dist config_file

  bucket_website_domain="${FRONTEND_BUCKET}.s3-website-${AWS_REGION}.amazonaws.com"
  existing_dist="$(
    aws_profile cloudfront list-distributions \
      --query "DistributionList.Items[?Aliases.Items && contains(Aliases.Items, '${FRONTEND_DOMAIN}')] | [0]" \
      --output json
  )"

  config_file="$(mktemp)"
  jq -n \
    --arg frontend_domain "$FRONTEND_DOMAIN" \
    --arg bucket_website_domain "$bucket_website_domain" \
    --arg cert_arn "$FRONTEND_CERT_ARN" \
    --arg caller_reference "${APP_NAME}-${FRONTEND_DOMAIN}-$(date +%s)" \
    '{
      CallerReference: $caller_reference,
      Aliases: {Quantity: 1, Items: [$frontend_domain]},
      DefaultRootObject: "index.html",
      Origins: {
        Quantity: 1,
        Items: [
          {
            Id: "frontend-s3-origin",
            DomainName: $bucket_website_domain,
            CustomOriginConfig: {
              HTTPPort: 80,
              HTTPSPort: 443,
              OriginProtocolPolicy: "http-only",
              OriginSslProtocols: {Quantity: 1, Items: ["TLSv1.2"]},
              OriginReadTimeout: 30,
              OriginKeepaliveTimeout: 5
            }
          }
        ]
      },
      DefaultCacheBehavior: {
        TargetOriginId: "frontend-s3-origin",
        ViewerProtocolPolicy: "redirect-to-https",
        AllowedMethods: {
          Quantity: 2,
          Items: ["GET", "HEAD"],
          CachedMethods: {Quantity: 2, Items: ["GET", "HEAD"]}
        },
        Compress: true,
        CachePolicyId: "658327ea-f89d-4fab-a63d-7e88639e58f6"
      },
      CustomErrorResponses: {
        Quantity: 2,
        Items: [
          {ErrorCode: 403, ResponsePagePath: "/index.html", ResponseCode: "200", ErrorCachingMinTTL: 0},
          {ErrorCode: 404, ResponsePagePath: "/index.html", ResponseCode: "200", ErrorCachingMinTTL: 0}
        ]
      },
      Comment: "Managed by whatif-worldcup-manager deploy script",
      PriceClass: "PriceClass_100",
      Enabled: true,
      ViewerCertificate: {
        ACMCertificateArn: $cert_arn,
        SSLSupportMethod: "sni-only",
        MinimumProtocolVersion: "TLSv1.2_2021",
        Certificate: $cert_arn,
        CertificateSource: "acm"
      },
      Restrictions: {
        GeoRestriction: {
          RestrictionType: "none",
          Quantity: 0
        }
      },
      HttpVersion: "http2",
      IsIPV6Enabled: true
    }' >"$config_file"

  distribution_id="$(jq -r '.Id // empty' <<<"$existing_dist")"
  if [[ -z "$distribution_id" ]]; then
    log "Creating CloudFront distribution for ${FRONTEND_DOMAIN}"
    distribution_id="$(
      aws_profile cloudfront create-distribution \
        --distribution-config "file://${config_file}" \
        --query 'Distribution.Id' \
        --output text
    )"
  else
    log "Reusing CloudFront distribution ${distribution_id} for ${FRONTEND_DOMAIN}"
  fi

  wait_for_distribution "$distribution_id"
  FRONTEND_DISTRIBUTION_ID="$distribution_id"
  FRONTEND_DISTRIBUTION_DOMAIN="$(
    aws_profile cloudfront get-distribution \
      --id "$distribution_id" \
      --query 'Distribution.DomainName' \
      --output text
  )"

  rm -f "$config_file"
}

build_and_sync_frontend() {
  log "Building frontend with API base ${API_DOMAIN}"
  (
    cd "$FRONTEND_DIR"
    npm ci
    VITE_API_BASE_URL="https://${API_DOMAIN}" npm run build
  )

  log "Uploading frontend assets to s3://${FRONTEND_BUCKET}"
  aws_region "$AWS_REGION" s3 sync "${FRONTEND_DIR}/dist/" "s3://${FRONTEND_BUCKET}/" --delete >/dev/null
}

ensure_ecr_repo() {
  if aws_region "$AWS_REGION" ecr describe-repositories --repository-names "$ECR_REPO" >/dev/null 2>&1; then
    log "ECR repository ${ECR_REPO} already exists"
  else
    log "Creating ECR repository ${ECR_REPO}"
    aws_region "$AWS_REGION" ecr create-repository --repository-name "$ECR_REPO" >/dev/null
  fi
}

ensure_app_runner_role() {
  if aws_profile iam get-role --role-name "$APP_RUNNER_ROLE_NAME" >/dev/null 2>&1; then
    log "IAM role ${APP_RUNNER_ROLE_NAME} already exists"
  else
    log "Creating IAM role ${APP_RUNNER_ROLE_NAME}"
    local trust_policy
    trust_policy="$(mktemp)"
    cat >"$trust_policy" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "build.apprunner.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON
    aws_profile iam create-role \
      --role-name "$APP_RUNNER_ROLE_NAME" \
      --assume-role-policy-document "file://${trust_policy}" >/dev/null
    rm -f "$trust_policy"
  fi

  aws_profile iam attach-role-policy \
    --role-name "$APP_RUNNER_ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess >/dev/null

  APP_RUNNER_ROLE_ARN="$(
    aws_profile iam get-role \
      --role-name "$APP_RUNNER_ROLE_NAME" \
      --query 'Role.Arn' \
      --output text
  )"
}

build_and_push_backend() {
  ACCOUNT_ID="$(
    aws_profile sts get-caller-identity \
      --query 'Account' \
      --output text
  )"
  local repository_uri image_tag image_uri

  repository_uri="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"
  image_tag="$(date +%Y%m%d%H%M%S)"
  image_uri="${repository_uri}:${image_tag}"

  log "Authenticating Docker to ECR"
  aws_region "$AWS_REGION" ecr get-login-password \
    | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com" >/dev/null

  log "Building and pushing linux/amd64 backend image ${image_uri}"
  docker buildx build \
    --platform linux/amd64 \
    --tag "$image_uri" \
    --push \
    "$BACKEND_DIR"

  BACKEND_IMAGE_URI="$image_uri"
}

ensure_autoscaling_configuration() {
  local existing_arn
  existing_arn="$(
    aws_region "$AWS_REGION" apprunner list-auto-scaling-configurations \
      --query "AutoScalingConfigurationSummaryList[?AutoScalingConfigurationName=='${APP_RUNNER_AUTOSCALING_NAME}' && Status=='ACTIVE'] | [0].AutoScalingConfigurationArn" \
      --output text
  )"

  if [[ -z "$existing_arn" || "$existing_arn" == "None" ]]; then
    log "Creating App Runner auto scaling configuration ${APP_RUNNER_AUTOSCALING_NAME}"
    existing_arn="$(
      aws_region "$AWS_REGION" apprunner create-auto-scaling-configuration \
        --auto-scaling-configuration-name "$APP_RUNNER_AUTOSCALING_NAME" \
        --max-concurrency 100 \
        --min-size 1 \
        --max-size 1 \
        --query 'AutoScalingConfiguration.AutoScalingConfigurationArn' \
        --output text
    )"
  fi

  APP_RUNNER_AUTOSCALING_ARN="$existing_arn"
}

ensure_app_runner_service() {
  local service_arn existing_service existing_status service_config
  existing_service="$(
    aws_region "$AWS_REGION" apprunner list-services \
      --query "ServiceSummaryList[?ServiceName=='${APP_RUNNER_SERVICE_NAME}'] | [0].ServiceArn" \
      --output text
  )"

  if [[ -n "$existing_service" && "$existing_service" != "None" ]]; then
    existing_status="$(
      aws_region "$AWS_REGION" apprunner describe-service \
        --service-arn "$existing_service" \
        --query 'Service.Status' \
        --output text
    )"

    if [[ "$existing_status" == "CREATE_FAILED" ]]; then
      log "Deleting failed App Runner service ${APP_RUNNER_SERVICE_NAME}"
      aws_region "$AWS_REGION" apprunner delete-service --service-arn "$existing_service" >/dev/null
      wait_for_app_runner_service_deletion "$existing_service"
      existing_service=""
    fi
  fi

  service_config="$(mktemp)"
  jq -n \
    --arg service_name "$APP_RUNNER_SERVICE_NAME" \
    --arg image_identifier "$BACKEND_IMAGE_URI" \
    --arg access_role_arn "$APP_RUNNER_ROLE_ARN" \
    --arg autoscaling_arn "$APP_RUNNER_AUTOSCALING_ARN" \
    --arg allowed_origins "https://${FRONTEND_DOMAIN}" \
    '{
      ServiceName: $service_name,
      SourceConfiguration: {
        AutoDeploymentsEnabled: false,
        AuthenticationConfiguration: {
          AccessRoleArn: $access_role_arn
        },
        ImageRepository: {
          ImageIdentifier: $image_identifier,
          ImageRepositoryType: "ECR",
          ImageConfiguration: {
            Port: "8000",
            RuntimeEnvironmentVariables: {
              ALLOWED_ORIGINS: $allowed_origins,
              SESSION_COOKIE_SECURE: "true"
            }
          }
        }
      },
      InstanceConfiguration: {
        Cpu: "1024",
        Memory: "2048"
      },
      AutoScalingConfigurationArn: $autoscaling_arn,
      HealthCheckConfiguration: {
        Protocol: "HTTP",
        Path: "/health",
        Interval: 10,
        Timeout: 5,
        HealthyThreshold: 1,
        UnhealthyThreshold: 5
      },
      NetworkConfiguration: {
        IngressConfiguration: {
          IsPubliclyAccessible: true
        },
        EgressConfiguration: {
          EgressType: "DEFAULT"
        },
        IpAddressType: "IPV4"
      }
    }' >"$service_config"

  if [[ -z "$existing_service" || "$existing_service" == "None" ]]; then
    log "Creating App Runner service ${APP_RUNNER_SERVICE_NAME}"
    service_arn="$(
      aws_region "$AWS_REGION" apprunner create-service \
        --cli-input-json "file://${service_config}" \
        --query 'Service.ServiceArn' \
        --output text
    )"
  else
    log "Updating App Runner service ${APP_RUNNER_SERVICE_NAME}"
    service_arn="$existing_service"
    jq 'del(.ServiceName)' "$service_config" >"${service_config}.update"
    aws_region "$AWS_REGION" apprunner update-service \
      --service-arn "$service_arn" \
      --cli-input-json "file://${service_config}.update" >/dev/null
    rm -f "${service_config}.update"
  fi

  wait_for_app_runner_service "$service_arn"
  APP_RUNNER_SERVICE_ARN="$service_arn"
  APP_RUNNER_DEFAULT_URL="$(
    aws_region "$AWS_REGION" apprunner describe-service \
      --service-arn "$service_arn" \
      --query 'Service.ServiceUrl' \
      --output text
  )"

  rm -f "$service_config"
}

ensure_api_custom_domain() {
  local association_response dns_target existing_status
  association_response="$(
    aws_region "$AWS_REGION" apprunner describe-custom-domains \
      --service-arn "$APP_RUNNER_SERVICE_ARN" \
      --output json 2>/dev/null || true
  )"

  existing_status="$(
    jq -r '.CustomDomains[]? | select(.DomainName=="'"${API_DOMAIN}"'") | .Status' <<<"${association_response:-{}}" | head -n 1
  )"

  if [[ -z "$existing_status" || "$existing_status" == "null" ]]; then
    log "Associating App Runner custom domain ${API_DOMAIN}"
    association_response="$(
      aws_region "$AWS_REGION" apprunner associate-custom-domain \
        --service-arn "$APP_RUNNER_SERVICE_ARN" \
        --domain-name "$API_DOMAIN" \
        --no-enable-www-subdomain \
        --output json
    )"
  else
    log "Reusing existing App Runner custom domain association for ${API_DOMAIN}"
    association_response="$(
      aws_region "$AWS_REGION" apprunner describe-custom-domains \
        --service-arn "$APP_RUNNER_SERVICE_ARN" \
        --output json
    )"
  fi

  dns_target="$(
    jq -r '.DNSTarget // empty' <<<"$association_response" | head -n 1
  )"

  if [[ -z "$dns_target" || "$dns_target" == "null" ]]; then
    echo "Unable to determine App Runner DNS target for ${API_DOMAIN}" >&2
    exit 1
  fi

  upsert_record_file \
    "$HOSTED_ZONE_ID" \
    "$(json_escape "${API_DOMAIN}")" \
    "CNAME" \
    "$(json_escape "${dns_target}")"

  jq -c '
    .CustomDomains[]?
    | select(.DomainName=="'"${API_DOMAIN}"'")
    | .CertificateValidationRecords[]?
  ' <<<"$association_response" | while read -r record; do
    local name type value
    name="$(jq -r '.Name' <<<"$record")"
    type="$(jq -r '.Type' <<<"$record")"
    value="$(jq -r '.Value' <<<"$record")"

    if [[ "$name" != "null" && "$type" != "null" && "$value" != "null" ]]; then
      upsert_record_file \
        "$HOSTED_ZONE_ID" \
        "$(json_escape "${name}")" \
        "$type" \
        "$(json_escape "${value}")"
    fi
  done

  local status=""
  while true; do
    status="$(
      aws_region "$AWS_REGION" apprunner describe-custom-domains \
        --service-arn "$APP_RUNNER_SERVICE_ARN" \
        --query "CustomDomains[?DomainName=='${API_DOMAIN}'] | [0].Status" \
        --output text
    )"

    if [[ "$status" == "ACTIVE" || "$status" == "active" ]]; then
      break
    fi

    log "Waiting for App Runner custom domain ${API_DOMAIN}. Current status: ${status}"
    sleep 20
  done
}

discover_hosted_zone() {
  HOSTED_ZONE_ID="$(
    aws_profile route53 list-hosted-zones-by-name \
      --dns-name "$ROOT_DOMAIN" \
      --query "HostedZones[?Name=='${ROOT_DOMAIN}.'] | [0].Id" \
      --output text
  )"
  HOSTED_ZONE_ID="${HOSTED_ZONE_ID#/hostedzone/}"

  if [[ -z "$HOSTED_ZONE_ID" || "$HOSTED_ZONE_ID" == "None" ]]; then
    echo "Unable to find hosted zone for ${ROOT_DOMAIN}" >&2
    exit 1
  fi
}

main() {
  require_cmd aws
  require_cmd jq
  require_cmd docker
  require_cmd npm
  require_cmd python3

  log "Starting AWS deployment for ${FRONTEND_DOMAIN} and ${API_DOMAIN}"
  discover_hosted_zone
  ensure_bucket
  ensure_frontend_certificate
  ensure_cloudfront_distribution
  build_and_sync_frontend
  ensure_ecr_repo
  ensure_app_runner_role
  build_and_push_backend
  ensure_autoscaling_configuration
  ensure_app_runner_service
  ensure_api_custom_domain
  upsert_alias_record \
    "$HOSTED_ZONE_ID" \
    "$(json_escape "${FRONTEND_DOMAIN}")" \
    "$(json_escape "${FRONTEND_DISTRIBUTION_DOMAIN}")" \
    "Z2FDTNDATAQYW2"

  log "Deployment complete"
  echo "Frontend URL: https://${FRONTEND_DOMAIN}"
  echo "Backend URL: https://${API_DOMAIN}"
  echo "App Runner default URL: https://${APP_RUNNER_DEFAULT_URL}"
  echo "CloudFront domain: https://${FRONTEND_DISTRIBUTION_DOMAIN}"
}

main "$@"
