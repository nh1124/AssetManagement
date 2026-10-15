import type { AccountFlowAnalysis, MonthlyReport } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { ACCOUNT_TYPES } from '../db/forms';
import type { ProfitLoss } from './ReportReading';
import { KINDS, STATES, proposalEffect, reportFigures, reportGoals, reportWarnings, varianceRows } from './reportPresentation';
import type { VarianceAnalysis } from './useBreakdownData';

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
        `# ${startDate} 〜 ${endDate} の内訳`,
        '## 期間の内訳',
        table(['項目', '値'], reportFigures(report, profitLoss, currency).map((row) => [row.label, row.value])),
        '## 支出の注意点・ライフイベントの進捗',
        '### 支出の注意点',
        list(reportWarnings(report, currency).map((row) => `${row.title}：${row.description}`), 'レポートが挙げる支出の注意点はありません。'),
        '### ライフイベントの進捗',
        list(reportGoals(report).map((row) => `${row.title}：${row.description}`), 'この期間のライフイベントはありません。'),
        '## 予算と実績',
        ...(variance.plan_id === null ? ['対象の予算プランなし'] : []),
        table(['項目', '値'], [
            ['期間の予算合計', money(variance.total_budget)],
            ['期間の支出合計', money(variance.total_actual)],
            ['予算 − 支出', money(variance.total_variance)],
        ]),
        table(['分類', '期間の予算', '期間の支出', '予算 − 支出'], varianceRows(variance).map((row) => [row.category, money(row.budget), money(row.actual), money(row.variance)])),
        ...(!variance.items.length ? ['この期間の支出計画・実績はありません。'] : []),
        '## 口座・科目',
        table(['口座・科目', '種別', '借方', '貸方', '増減', '仕訳数'], flows.accounts.map((row) => [row.account_name, ACCOUNT_TYPES[row.account_type], money(row.total_debit), money(row.total_credit), money(row.normal_balance_delta), row.transaction_count])),
        ...(!flows.accounts.length ? ['この期間の口座の動きはありません。'] : []),
        '## 次にできること',
        list(report.action_proposals.map((proposal) => `${KINDS[proposal.kind]}（${proposal.applied ? '適用済み' : STATES[proposal.action_status ?? 'pending']}）：${proposalEffect(proposal, report, currency)}`), 'この期間の提案はありません。'),
    ].join('\n\n') + '\n';
}

export function breakdownCsv(data: BreakdownSnapshot, currency: string) {
    // A common header keeps both tables aligned in one worksheet; amounts stay numeric.
    const rows: Array<Array<string | number>> = [
        ['セクション', '分類・口座・科目', '種別', '期間の予算', '期間の支出', '予算 − 支出', '借方', '貸方', '増減', '仕訳数', '通貨'],
        ...varianceRows(data.variance).map((row) => ['予算と実績', row.category, '', row.budget, row.actual, row.variance, '', '', '', '', currency]),
        ...data.flows.accounts.map((row) => ['口座・科目', row.account_name, ACCOUNT_TYPES[row.account_type], '', '', '', row.total_debit, row.total_credit, row.normal_balance_delta, row.transaction_count, currency]),
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
