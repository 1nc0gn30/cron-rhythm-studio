"""Production Cron Schedule Catalog for cron-rhythm-studio.

Contains 40+ battle-tested production presets across Database, DevOps,
Security, Cache, Finance, Email, and Monitoring domains.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .models import CronPreset

PRESETS: List[CronPreset] = [
    # 1. Database & Backups
    CronPreset(
        id="db-backup-nightly-full",
        title="Nightly Full Database Backup",
        category="Database & Storage",
        expression="0 2 * * *",
        description="Executes a complete database snapshot and mysqldump/pg_dump every night at 2:00 AM.",
        tags=["database", "backup", "mysql", "postgres", "nightly"],
    ),
    CronPreset(
        id="db-wal-archive-hourly",
        title="Hourly WAL Archive Sync",
        category="Database & Storage",
        expression="0 * * * *",
        description="Flushes and uploads Write-Ahead Logs (WAL) to remote object storage at the top of every hour.",
        tags=["database", "postgres", "wal", "replication", "hourly"],
    ),
    CronPreset(
        id="db-vacuum-weekly-sunday",
        title="Weekly PostgreSQL VACUUM ANALYZE",
        category="Database & Storage",
        expression="0 3 * * 0",
        description="Performs database table maintenance, dead tuple reclamation, and query planner statistics update every Sunday at 3:00 AM.",
        tags=["database", "postgres", "vacuum", "maintenance", "weekly"],
    ),
    CronPreset(
        id="db-replica-check-15min",
        title="Database Replication Lag Check",
        category="Database & Storage",
        expression="*/15 * * * *",
        description="Inspects read-replica replication byte lag and emits metrics every 15 minutes.",
        tags=["database", "monitoring", "replication", "high-availability"],
    ),
    CronPreset(
        id="db-cold-storage-monthly",
        title="Monthly Offsite Cold Backup",
        category="Database & Storage",
        expression="0 4 1 * *",
        description="Generates encrypted long-term cold archive (AWS Glacier / Google Coldline) on the 1st of every month at 4:00 AM.",
        tags=["database", "compliance", "glacier", "cold-storage", "monthly"],
    ),
    CronPreset(
        id="db-redis-bgsave-daily",
        title="Daily Redis RDB Snapshot",
        category="Database & Storage",
        expression="30 3 * * *",
        description="Triggers Redis BGSAVE disk dump and persists RDB snapshot daily at 3:30 AM.",
        tags=["database", "redis", "cache", "snapshot"],
    ),

    # 2. Log Rotation & Housekeeping
    CronPreset(
        id="logrotate-daily-midnight",
        title="Daily Midnight Logrotate",
        category="Housekeeping",
        expression="0 0 * * *",
        description="Compresses, rotates, and indexes application and webserver log files every midnight.",
        tags=["logs", "linux", "logrotate", "disk-space", "daily"],
    ),
    CronPreset(
        id="tmp-cleanup-hourly",
        title="Hourly Temp Files Purge",
        category="Housekeeping",
        expression="15 * * * *",
        description="Removes orphaned temp files, PID locks, and unlinked upload chunks at 15 minutes past every hour.",
        tags=["cleanup", "tmp", "filesystem", "hourly"],
    ),
    CronPreset(
        id="docker-prune-weekly",
        title="Weekly Docker System Prune",
        category="Housekeeping",
        expression="0 4 * * 6",
        description="Purges unused Docker containers, dangling images, volumes, and build cache every Saturday at 4:00 AM.",
        tags=["docker", "containers", "cleanup", "devops", "weekly"],
    ),
    CronPreset(
        id="session-purge-nightly",
        title="Nightly Expired Web Sessions Purge",
        category="Housekeeping",
        expression="45 2 * * *",
        description="Deletes expired authentication tokens and stale session records from Redis/DB daily at 2:45 AM.",
        tags=["auth", "security", "sessions", "cleanup"],
    ),
    CronPreset(
        id="core-dump-archive-daily",
        title="Daily Crash Dump & Trace Archive",
        category="Housekeeping",
        expression="0 1 * * *",
        description="Compresses core dumps and stacktraces older than 48 hours daily at 1:00 AM.",
        tags=["debugging", "crashes", "storage"],
    ),

    # 3. Security & SSL
    CronPreset(
        id="ssl-letsencrypt-renew-biweekly",
        title="Bi-Weekly Let's Encrypt Certbot Renewal",
        category="Security & SSL",
        expression="0 0 1,15 * *",
        description="Runs certbot renewal check for TLS certificates on the 1st and 15th of every month at midnight.",
        tags=["ssl", "tls", "security", "certbot", "https"],
    ),
    CronPreset(
        id="ssl-cert-expiry-check-daily",
        title="Daily SSL Expiration Monitor",
        category="Security & SSL",
        expression="0 8 * * *",
        description="Probes domain certificates and alerts PagerDuty/Slack if expiry is within 14 days daily at 8:00 AM.",
        tags=["ssl", "monitoring", "alerts", "security"],
    ),
    CronPreset(
        id="vulnerability-scan-nightly",
        title="Nightly Container & CVE Vulnerability Scan",
        category="Security & SSL",
        expression="0 1 * * 1-5",
        description="Runs container vulnerability and dependency security scans every weekday at 1:00 AM.",
        tags=["security", "cve", "snyk", "trivy", "compliance"],
    ),
    CronPreset(
        id="ssh-failed-logins-audit",
        title="SSH Failed Logins Anomaly Audit",
        category="Security & SSL",
        expression="*/30 * * * *",
        description="Scans auth.log for brute-force SSH attempts and updates IP firewall blacklists every 30 minutes.",
        tags=["security", "ssh", "firewall", "fail2ban"],
    ),
    CronPreset(
        id="api-key-rotation-reminder",
        title="Quarterly API Key Rotation Notice",
        category="Security & SSL",
        expression="0 9 1 1,4,7,10 *",
        description="Dispatches quarterly compliance reminders for rotating master API keys on Jan, Apr, Jul, Oct 1st at 9:00 AM.",
        tags=["security", "compliance", "rotation", "quarterly"],
    ),

    # 4. Cache & Performance
    CronPreset(
        id="cache-warm-morning",
        title="Morning API Cache Warmer",
        category="Performance",
        expression="45 7 * * 1-5",
        description="Pre-populates home feeds and analytics dashboards before peak traffic at 7:45 AM Monday through Friday.",
        tags=["cache", "performance", "redis", "warmup"],
    ),
    CronPreset(
        id="cdn-purge-hourly",
        title="Hourly CDN Invalidation Check",
        category="Performance",
        expression="50 * * * *",
        description="Validates CDN stale-while-revalidate headers and invalidates updated static assets at :50 of every hour.",
        tags=["cdn", "cloudflare", "fastly", "cache"],
    ),
    CronPreset(
        id="sitemap-regenerate-nightly",
        title="Nightly SEO Sitemap Generator",
        category="Performance",
        expression="15 3 * * *",
        description="Crawls public routes, builds sitemap.xml, and pings search engine webmaster APIs daily at 3:15 AM.",
        tags=["seo", "sitemap", "web", "google"],
    ),
    CronPreset(
        id="page-speed-audit-daily",
        title="Daily Core Web Vitals Audit",
        category="Performance",
        expression="0 5 * * *",
        description="Executes headless Lighthouse runs against key landing pages daily at 5:00 AM.",
        tags=["lighthouse", "webvitals", "speed", "frontend"],
    ),

    # 5. Monitoring & Health
    CronPreset(
        id="health-check-5min",
        title="5-Minute Uptime Health Probe",
        category="Monitoring",
        expression="*/5 * * * *",
        description="Pings load balancer /health endpoints and checks database responsiveness every 5 minutes.",
        tags=["monitoring", "health", "uptime", "probe"],
    ),
    CronPreset(
        id="disk-space-alert-hourly",
        title="Hourly Disk Space & Inode Monitor",
        category="Monitoring",
        expression="0 * * * *",
        description="Checks root and volume storage mounts and alerts ops if disk usage exceeds 85% every hour.",
        tags=["monitoring", "disk", "storage", "alerts"],
    ),
    CronPreset(
        id="dead-man-switch-10min",
        title="Dead Man's Snitch Heartbeat",
        category="Monitoring",
        expression="*/10 * * * *",
        description="Sends external watchdog heartbeat ping to confirm cron daemon vitality every 10 minutes.",
        tags=["monitoring", "heartbeat", "watchdog"],
    ),
    CronPreset(
        id="queue-backlog-monitor-1min",
        title="Continuous Queue Backlog Monitor",
        category="Monitoring",
        expression="* * * * *",
        description="Polls SQS, RabbitMQ, or Celery queues for processing latency and dead letters every minute.",
        tags=["queues", "celery", "rabbitmq", "monitoring"],
    ),
    CronPreset(
        id="ssl-ocsp-staple-refresh",
        title="OCSP Staple Status Refresh",
        category="Monitoring",
        expression="0 */4 * * *",
        description="Fetches fresh OCSP responses for NGINX/Envoy TLS handshakes every 4 hours.",
        tags=["ssl", "ocsp", "tls", "networking"],
    ),

    # 6. Emails & Notifications
    CronPreset(
        id="email-weekly-team-digest",
        title="Monday Morning Executive Digest",
        category="Emails & Notifications",
        expression="0 9 * * 1",
        description="Aggregates weekly metrics and sends executive summary email every Monday at 9:00 AM.",
        tags=["email", "digest", "reports", "weekly"],
    ),
    CronPreset(
        id="email-daily-standup-summary",
        title="Weekday Morning Standup Summary",
        category="Emails & Notifications",
        expression="0 8 * * 1-5",
        description="Compiles team Jira tickets and GitHub PR review requests weekdays at 8:00 AM.",
        tags=["email", "standup", "jira", "github", "daily"],
    ),
    CronPreset(
        id="email-friday-pulse-recap",
        title="Friday Team Wrap-up Recap",
        category="Emails & Notifications",
        expression="0 17 * * 5",
        description="Sends weekly deployment wins and incident retrospective recap every Friday at 5:00 PM.",
        tags=["email", "recap", "friday", "team"],
    ),
    CronPreset(
        id="email-inactive-user-nudge",
        title="Bi-Weekly Dormant User Re-engagement",
        category="Emails & Notifications",
        expression="0 14 * * 2,4",
        description="Triggers drip re-engagement emails for users inactive for 30+ days on Tuesday and Thursday at 2:00 PM.",
        tags=["email", "growth", "marketing", "retention"],
    ),
    CronPreset(
        id="email-newsletter-broadcast",
        title="Weekly Wednesday Newsletter Dispatch",
        category="Emails & Notifications",
        expression="0 11 * * 3",
        description="Dispatches scheduled subscriber newsletter batch every Wednesday at 11:00 AM.",
        tags=["email", "newsletter", "marketing", "weekly"],
    ),

    # 7. Billing & Finance
    CronPreset(
        id="billing-monthly-invoice-run",
        title="1st of Month Billing & Invoice Run",
        category="Billing & Finance",
        expression="0 0 1 * *",
        description="Generates Stripe customer invoices and aggregates usage-based meters on the 1st of every month at midnight.",
        tags=["billing", "invoices", "stripe", "finance", "monthly"],
    ),
    CronPreset(
        id="billing-dunning-retry-daily",
        title="Daily Smart Payment Retries & Dunning",
        category="Billing & Finance",
        expression="0 10 * * *",
        description="Retries failed subscription payments and delivers dunning notices daily at 10:00 AM.",
        tags=["billing", "payments", "dunning", "revenue"],
    ),
    CronPreset(
        id="finance-eod-reconciliation",
        title="End-of-Day Transaction Settlement",
        category="Billing & Finance",
        expression="0 21 * * 1-5",
        description="Reconciles bank ledger balances with internal transaction records weekdays at 9:00 PM.",
        tags=["finance", "accounting", "settlement", "eod"],
    ),
    CronPreset(
        id="finance-fx-rates-sync-hourly",
        title="Hourly Market Currency FX Sync",
        category="Billing & Finance",
        expression="5 9-17 * * 1-5",
        description="Fetches live forex and currency conversion rates during market hours at 5 minutes past each hour.",
        tags=["finance", "forex", "fx", "currency"],
    ),
    CronPreset(
        id="finance-payroll-biweekly",
        title="Bi-Weekly Payroll Direct Deposit Trigger",
        category="Billing & Finance",
        expression="0 6 15,28 * *",
        description="Executes payroll ACH batch transfers on the 15th and 28th of every month at 6:00 AM.",
        tags=["finance", "payroll", "ach", "banking"],
    ),

    # 8. DevOps & CI/CD
    CronPreset(
        id="ci-staging-environment-reset",
        title="Weekly Staging Environment Reset",
        category="DevOps & CI/CD",
        expression="0 23 * * 5",
        description="Seeds staging database with sanitized production data and redeploys main branch Friday at 11:00 PM.",
        tags=["devops", "staging", "ci-cd", "testing"],
    ),
    CronPreset(
        id="ci-git-repo-mirror-sync",
        title="Git Remote Backup Mirror Sync",
        category="DevOps & CI/CD",
        expression="*/15 * * * *",
        description="Synchronizes all GitHub repository commits and tags to secondary GitLab/Bitbucket backup every 15 minutes.",
        tags=["git", "backup", "github", "devops"],
    ),
    CronPreset(
        id="ci-ephemeral-env-cleanup",
        title="Weekday Preview Environment Teardown",
        category="DevOps & CI/CD",
        expression="0 19 * * 1-5",
        description="Destroys idle pull-request preview environments to save cloud costs weekdays at 7:00 PM.",
        tags=["kubernetes", "cloud", "aws", "costs", "devops"],
    ),
    CronPreset(
        id="k8s-pod-restart-graceful",
        title="Weekly Graceful Pod Recycling",
        category="DevOps & CI/CD",
        expression="0 4 * * 0",
        description="Performs zero-downtime rolling rollout restart of memory-intensive worker pods Sunday at 4:00 AM.",
        tags=["kubernetes", "k8s", "pods", "devops"],
    ),
    CronPreset(
        id="telemetry-metrics-rollup-daily",
        title="Daily Telemetry & Metrics Rollup",
        category="DevOps & CI/CD",
        expression="30 0 * * *",
        description="Compacts high-resolution 1-second Prometheus metrics into 1-hour rollup tables daily at 00:30 AM.",
        tags=["prometheus", "telemetry", "metrics", "observability"],
    ),

    # 9. IoT & Edge Computing
    CronPreset(
        id="iot-sensor-calibration-hourly",
        title="Hourly IoT Sensor Auto-Zero Calibration",
        category="IoT & Edge",
        expression="0 * * * *",
        description="Sends calibration offsets to edge telemetry devices at the top of every hour.",
        tags=["iot", "hardware", "sensors", "edge"],
    ),
    CronPreset(
        id="iot-firmware-ota-check",
        title="Weekly Firmware OTA Update Check",
        category="IoT & Edge",
        expression="0 3 * * 2",
        description="Polls firmware artifact server for signed device firmware updates Tuesday at 3:00 AM.",
        tags=["iot", "ota", "firmware", "embedded"],
    ),
    CronPreset(
        id="iot-battery-telemetry-daily",
        title="Daily Edge Battery Level Aggregation",
        category="IoT & Edge",
        expression="0 12 * * *",
        description="Gathers battery voltage and degradation metrics from field deployed nodes daily at 12:00 PM.",
        tags=["iot", "telemetry", "battery", "field"],
    ),
]

_PRESET_MAP: Dict[str, CronPreset] = {p.id: p for p in PRESETS}


def list_presets(category: Optional[str] = None) -> List[CronPreset]:
    """List all available production cron presets, optionally filtered by category.
    
    Args:
        category: Optional category name.
        
    Returns:
        List of CronPreset objects.
    """
    if category is None:
        return list(PRESETS)
    cat_lower = category.strip().lower()
    return [p for p in PRESETS if p.category.lower() == cat_lower]


def get_preset(preset_id: str) -> Optional[CronPreset]:
    """Retrieve a preset by its unique ID."""
    return _PRESET_MAP.get(preset_id.strip())


def search_presets(query: str) -> List[CronPreset]:
    """Search presets by matching query against id, title, description, category, expression, and tags.
    
    Args:
        query: Search term string.
        
    Returns:
        Matching list of CronPreset objects.
    """
    q = query.strip().lower()
    if not q:
        return list(PRESETS)

    results: List[CronPreset] = []
    for p in PRESETS:
        match_score = (
            q in p.id.lower()
            or q in p.title.lower()
            or q in p.description.lower()
            or q in p.category.lower()
            or q in p.expression.lower()
            or any(q in tag.lower() for tag in p.tags)
        )
        if match_score:
            results.append(p)
    return results


def get_categories() -> List[str]:
    """Get sorted list of all unique preset category names."""
    cats = sorted(list({p.category for p in PRESETS}))
    return cats
