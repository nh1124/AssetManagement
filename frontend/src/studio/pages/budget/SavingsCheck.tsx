import type { SavingsCheck as Check, SavingsCheckGroup } from '../../../api/goalBudget';
import { formatCurrency } from '../../../utils/currency';

const LABELS: Record<SavingsCheckGroup['key'], string> = {
    existing: 'ユーザー指定の積立（定義・手入力・ゴール外の取り置き）',
    products: '消耗品・固定資産の取り置き',
    near: '近いライフイベントの取り置き',
    rest: 'ゴールの積立（遠いイベント・残り）',
};

/** U9: the month's budgeted savings against the whole monthly need; the breakdown opens when short. */
export default function SavingsCheck({ check, currency }: { check: Check; currency: string }) {
    const money = (amount: number) => formatCurrency(amount, currency);
    const short = check.shortfall > 0;
    const over = check.budgeted - check.need;
    const total = check.goal?.savings_source === 'required' ? 'イベントの必要額の合計' : '月の積立';
    return <details open={short} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] px-5 py-3 text-sm">
        <summary className="cursor-pointer">
            <span role={short ? 'alert' : undefined} className={short ? 'font-medium text-[var(--studio-warning)]' : 'text-[var(--studio-text-muted)]'}>
                {short ? `積立が必要額より ${money(check.shortfall)} 少なくなっています` : over >= 1 ? `積立は必要額を ${money(over)} 上回っています` : '積立は必要額と一致しています'}
            </span>
            <span className="ml-2 text-xs tabular-nums text-[var(--studio-text-muted)]">予算の積立 {money(check.budgeted)} ／ 必要額 {money(check.need)}</span>
        </summary>
        <table className="mt-3 w-full max-w-2xl text-left text-xs">
            <thead className="text-[var(--studio-text-muted)]"><tr><th scope="col" className="py-1 font-medium">必要額の内訳</th><th scope="col" className="py-1 text-right font-medium">月額</th></tr></thead>
            <tbody className="divide-y divide-[var(--studio-border)]">
                {check.groups.map((group) => <tr key={group.key}>
                    <th scope="row" className="py-2 pr-4 font-normal">{LABELS[group.key]}
                        {group.items.length > 0 && <span className="mt-1 block text-[var(--studio-text-muted)]">{group.items.map((item) => `${item.name} ${money(item.amount)}`).join('、')}</span>}
                        {group.key === 'rest' && <span className="mt-1 block text-[var(--studio-text-muted)]">{check.goal ? `ゴール「${check.goal.name}」の${total} ${money(check.goal.monthly_savings)} から上の項目を除いた残り` : 'ゴールがないため含みません'}</span>}
                    </th>
                    <td className="py-2 text-right align-top tabular-nums">{money(group.need)}</td>
                </tr>)}
                <tr className="font-medium"><th scope="row" className="py-2">必要額の合計</th><td className="py-2 text-right tabular-nums">{money(check.need)}</td></tr>
                <tr><th scope="row" className="py-2 font-normal">予算の積立（資産口座・取り置きへの配分の合計）</th><td className="py-2 text-right tabular-nums">{money(check.budgeted)}</td></tr>
                {short && <tr className="font-medium text-[var(--studio-warning)]"><th scope="row" className="py-2">不足</th><td className="py-2 text-right tabular-nums">{money(check.shortfall)}</td></tr>}
            </tbody>
        </table>
    </details>;
}
