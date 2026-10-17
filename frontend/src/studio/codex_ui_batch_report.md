UI batch report — 2026-10-18

Paths are relative to /home/nh112/AssetManagement/frontend/src/studio.

1. Overlay busy state: optional busy defaults to false; busy disables × and blocks × / Esc / backdrop dismissal. components/Overlay.tsx:31, :57, :59, :80.
   Existing guards migrated to busy: pages/Household.tsx:45; pages/goals/GoalBudgetReflection.tsx:158, GoalSwitchOverlay.tsx:16, GoalArchive.tsx:42, GoalCapsuleLinks.tsx:148, GoalWorkspace.tsx:95 and :101, GoalConditions.tsx:96, Milestones.tsx:74, LifeEventLinkDetails.tsx:23, LifeEventGraph.tsx:172 / :179 / :192, LifeEventList.tsx:37, ScenarioList.tsx:101. Review is covered below. Shared editor cancel buttons remain disabled during writes.
2. Unsaved review draft: PeriodReading tracks dirty state and forwards it to the existing period-change guard. Closing a dirty draft asks 「未保存の振り返りがあります。変更を破棄して閉じますか？」 with 「破棄して閉じる」. Cancellation retains the draft; discard clears dirty state; saving still closes normally. pages/report/Review.tsx:57, :63, :66, :67, :81. Existing period-change confirmation preserved.
3. Destructive confirmations: labels containing 削除 or 破棄 use var(--studio-danger) and white text; other labels retain accent styling. API unchanged. components/Confirm.tsx:9, :12.
4. Scenario column: renamed 前提条件 to 条件の達成確率. pages/goals/ScenarioList.tsx:71.
5. Ledger empty state: retained 「この月の記録はありません。」 and added a buttonClass Link to /record labelled 「取引を記録」. pages/ledger/Records.tsx:9, :148. Ledger uses a separate Unmatched component; its empty text is now 「未照合の明細はありません。」 without a link. pages/ledger/Unmatched.tsx:104.
6. Earmark amount labels: standardized to 確保額, retaining 通貨別 where applicable. pages/assets/Earmarks.tsx:50, AccountEarmarks.tsx:141; pages/goals/GoalArchive.tsx:45, GoalWorkspace.tsx:77 and :91, LifeEventList.tsx:42.
   Preserved 用途確保 in pages/assets/Accounts.tsx:29 and pages/db/forms.tsx:18 (account roles), and pages/RecordForm.tsx:30 (transaction kind): these do not label amounts. Preserved goals' 確保済み progress labels, existing 確保額（現在） qualifiers, and GoalProjection.tsx:48 explanatory text to retain meaning.
7. Asset accounts: existing getAccounts data includes Account.balance. Replaced the per-row 種別 column with 残高, using formatCurrency with client currency and tabular-nums; kept type group headings. No new API calls. pages/assets/Accounts.tsx:8, :116, :129.

Verification:
- PASS: cd /home/nh112/AssetManagement/frontend && npx tsc -b && npx eslint src/studio (exit 0).
- PASS: git diff --check.
- PASS: in-memory component-handler checks for busy/default dismissal, destructive styles, draft cancel/discard/clean/save/busy states, and existing period-change confirmation. No test files added.
- Browser/visual checks not performed; verification used the required compiler/linter and mocked component handlers.

Skipped: no requested UI items. docs/STATUS updates omitted because this task explicitly prohibits docs changes. No backend/, mcp/, docs/, mobile/, or other source files changed. No commits or real-data operations.

Report delivery: writing /home/nh112/p7work/codex_ui_batch_report.md failed with OSError 30 (read-only filesystem). This copy is saved inside the permitted Studio workspace because the environment does not permit approval escalation.
