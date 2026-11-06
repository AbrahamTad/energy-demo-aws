# EnergyDemo scope and safety

Work only in this isolated EnergyDemo worktree and its current authorized branch. Never inspect,
connect to, modify or copy data from other projects. Preserve existing work and backups.

Contact changes must stay separate from unrelated Admin/TOTP code. Karl's admin membership remains
ON HOLD. AWS writes, emails, secret provisioning, Terraform Apply, commits, pushes and deployment
require separate explicit authorization. Do not read customer records or secret values for reviews.

For verbose local checks, use the global summary wrapper with CODEX_SUMMARY_LOG_DIR set to an
allowed private directory under .local/. Inspect full logs for failures; never skip required checks.
