import type { AccountFlowAnalysis, MonthlyReport } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { ACCOUNT_TYPES } from '../db/forms';
import type { ProfitLoss } from './ReportReading';
import { KINDS, proposalEffect, reportFigures, reportGoals, reportWarnings, varianceRows } from './reportPresentation';
import type { VarianceAnalysis } from './useBreakdownData';
import { tr } from '../../i18n';

interface BreakdownSnapshot {
    report: MonthlyReport;
    profitLoss: ProfitLoss;
    variance: VarianceAnalysis;
    flows: AccountFlowAnalysis;
}

function table(headers: string[], rows: Array<Array<string | number>>) {
    // Escape backslashes first so an existing escape cannot expose a pipe delimiter.
    const cell = (value: string | number) => String(value).replace(/\\/g, '\\\\').replace(/\|/g, '\\|').replace(/\r\n|\r|\n/g, '<br>');
    const row = (values: Array<string | number>) => `| ${values.map(cell).join(' | ')} |`;
    return [row(headers), row(headers.map(() => '---')), ...rows.map(row)].join('\n');
}

function list(rows: string[], empty: string) {
    return (rows.length ? rows : [empty]).map((row) => `- ${row.replace(/\r\n|\r|\n/g, ' ')}`).join('\n');
}

export function breakdownMarkdown(data: BreakdownSnapshot, startDate: string, endDate: string, currency: string) {
    const { report, profitLoss, variance, flows } = data;
    const money = (amount: number) => formatCurrency(amount, currency);
    return [
        tr(`# ${startDate} 〜 ${endDate} の内訳`, `# Breakdown for ${startDate} to ${endDate}`),
        tr('## 期間の内訳', '## The period'),
        table([tr('項目', 'Item'), tr('値', 'Value')], reportFigures(report, profitLoss, currency).map((row) => [row.label, row.value])),
        tr('## 支出の注意点・ライフイベントの進捗', '## Spending notes and life event progress'),
        tr('### 支出の注意点', '### Spending notes'),
        list(reportWarnings(report, currency).map((row) => `${row.title}${tr('：', ': ')}${row.description}`), tr('レポートが挙げる支出の注意点はありません。', 'The report notes nothing about spending.')),
        tr('### ライフイベントの進捗', '### Life event progress'),
        list(reportGoals(report).map((row) => `${row.title}${tr('：', ': ')}${row.description}`), tr('この期間のライフイベントはありません。', 'No life events in this period.')),
        tr('## 予算と実績', '## Budget and actuals'),
        ...(variance.plan_id === null ? [tr('保存した計画の行なし', 'No saved plan lines')] : []),
        table([tr('項目', 'Item'), tr('値', 'Value')], [
            [tr('期間の予算合計', 'Budget in the period'), money(variance.total_budget)],
            [tr('期間の支出合計', 'Spending in the period'), money(variance.total_actual)],
            [tr('予算 − 支出', 'Budget − spending'), money(variance.total_variance)],
        ]),
        table([tr('分類', 'Category'), tr('期間の予算', 'Budget'), tr('期間の支出', 'Spending'), tr('予算 − 支出', 'Budget − spending')], varianceRows(variance).map((row) => [row.category, money(row.budget), money(row.actual), money(row.variance)])),
        ...(!variance.items.length ? [tr('この期間の支出計画・実績はありません。', 'No spending plan or actuals in this period.')] : []),
        tr('## 口座・科目', '## Accounts'),
        table([tr('口座・科目', 'Account'), tr('種別', 'Type'), tr('借方', 'Debit'), tr('貸方', 'Credit'), tr('増減', 'Change'), tr('仕訳数', 'Entries')], flows.accounts.map((row) => [row.account_name, ACCOUNT_TYPES[row.account_type], money(row.total_debit), money(row.total_credit), money(row.normal_balance_delta), row.transaction_count])),
        ...(!flows.accounts.length ? [tr('この期間の口座の動きはありません。', 'No account movements in this period.')] : []),
        tr('## 次にできること', '## What you can do next'),
        list(report.action_proposals.map((proposal) => `${KINDS[proposal.kind]}${tr('：', ': ')}${proposalEffect(proposal, report, currency)}`), tr('この期間の提案はありません。', 'No suggestions for this period.')),
    ].join('\n\n') + '\n';
}

export function breakdownCsv(data: BreakdownSnapshot, currency: string) {
    // A common header keeps both tables aligned in one worksheet; amounts stay numeric.
    const rows: Array<Array<string | number>> = [
        [tr('セクション', 'Section'), tr('分類・口座・科目', 'Category / account'), tr('種別', 'Type'), tr('期間の予算', 'Budget'), tr('期間の支出', 'Spending'), tr('予算 − 支出', 'Budget − spending'), tr('借方', 'Debit'), tr('貸方', 'Credit'), tr('増減', 'Change'), tr('仕訳数', 'Entries'), tr('通貨', 'Currency')],
        ...varianceRows(data.variance).map((row) => [tr('予算と実績', 'Budget and actuals'), row.category, '', row.budget, row.actual, row.variance, '', '', '', '', currency]),
        ...data.flows.accounts.map((row) => [tr('口座・科目', 'Accounts'), row.account_name, ACCOUNT_TYPES[row.account_type], '', '', '', row.total_debit, row.total_credit, row.normal_balance_delta, row.transaction_count, currency]),
    ];
    // Excel needs a UTF-8 BOM for Japanese labels and CRLF for record boundaries.
    // Quote text, leave finite numbers bare: a quoted amount lands in Excel as
    // a string and will not add up, and a number holds no comma or quote to escape.
    const field = (value: string | number) => typeof value === 'number' && Number.isFinite(value)
        ? String(value)
        : `"${String(value).replace(/"/g, '""')}"`;
    return '\uFEFF' + rows.map((row) => row.map(field).join(',')).join('\r\n') + '\r\n';
}

export function downloadBreakdown(content: string, filename: string, type: string) {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    try {
        link.click();
    } finally {
        link.remove();
        // Give the browser time to start consuming the Blob before revoking its URL.
        window.setTimeout(() => URL.revokeObjectURL(url), 0);
    }
}
