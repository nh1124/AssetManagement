import { useState, type FormEvent } from 'react';
import { autoUpdateExchangeRates, createExchangeRate, deleteExchangeRate, getExchangeRates } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { ExchangeRate, ExchangeRateAutoUpdateResult } from '../../../types';
import { useResource } from '../../useResource';
import { DataTable, Feedback, Field } from './Database';
import { buttonClass, inputClass, primaryClass, today, useMutation } from './forms';

function FxForClient({ currency }: { currency: string }) {
    const resource = useResource(getExchangeRates);
    const mutation = useMutation();
    const [base, setBase] = useState('USD');
    const [quote, setQuote] = useState(currency);
    const [rate, setRate] = useState('');
    const [date, setDate] = useState(today);
    const [fetched, setFetched] = useState<ExchangeRateAutoUpdateResult | null>(null);
    const disabled = mutation.busy || resource.loading || Boolean(resource.error);
    const add = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (disabled || base === quote || !Number.isFinite(Number(rate)) || Number(rate) <= 0) return;
        void mutation.run(() => createExchangeRate({ base_currency: base, quote_currency: quote, rate: Number(rate), as_of_date: date, source: 'manual' }), '為替レートを登録しました。', () => { setRate(''); resource.reload(); });
    };
    const remove = (row: ExchangeRate) => {
        if (disabled || !window.confirm(`${row.base_currency} → ${row.quote_currency}（${row.as_of_date}、レート ${row.rate}）を削除しますか？`)) return;
        void mutation.run(() => deleteExchangeRate(row.id), '為替レートを削除しました。', () => {
            resource.setData((previous) => previous?.filter((rate) => rate.id !== row.id) ?? null);
            resource.reload();
        });
    };
    const autoUpdate = () => {
        if (disabled) return;
        let result: ExchangeRateAutoUpdateResult | null = null;
        void mutation.run(async () => { result = await autoUpdateExchangeRates(); }, '自動更新の結果を取得しました。', () => { setFetched(result); resource.reload(); });
    };
    return <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">為替レート</h2><p className="mt-1 text-xs text-[var(--studio-text-muted)]">基準通貨1単位に対する換算先通貨のレート。クライアントの通貨：{currency}</p></div><div className="flex gap-2"><button type="button" disabled={disabled} onClick={autoUpdate} className={buttonClass}>自動更新</button><button type="button" disabled={mutation.busy || resource.loading} onClick={resource.reload} className={buttonClass}>再読み込み</button></div></div>
        <Feedback loading={resource.loading} error={mutation.error || resource.error} message={mutation.message} />
        {fetched && <div className="space-y-2 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5 text-sm" role="status">
            <p className="font-medium">換算先：{fetched.target_currency} ／ 取得：{fetched.updated.length}件 ／ スキップ：{fetched.skipped.length}件 ／ 失敗：{fetched.errors.length}件</p>
            {fetched.updated.map((row) => <p key={row.id}>{row.base_currency} → {row.quote_currency}：{row.rate}（{row.as_of_date}、{row.source}）</p>)}
            {fetched.skipped.map((row, index) => <p key={`skip-${index}`} className="text-[var(--studio-text-muted)]">{row.base_currency} → {row.quote_currency}：{row.reason}</p>)}
            {fetched.errors.map((row, index) => <p key={`error-${index}`} className="text-[var(--studio-danger)]">{row.base_currency} → {row.quote_currency}：{row.error}</p>)}
            {!fetched.detected_pairs.length && <p className="text-[var(--studio-text-muted)]">更新対象の通貨ペアはありませんでした。</p>}
        </div>}
        <form onSubmit={add} className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <h3 className="text-sm font-semibold">新規作成</h3>
            <fieldset disabled={disabled} className="grid items-end gap-4 md:grid-cols-2 xl:grid-cols-5">
                <Field label="基準通貨"><input required pattern="[A-Z]{3}" maxLength={3} value={base} onChange={(event) => setBase(event.target.value.toUpperCase())} className={inputClass} /></Field>
                <Field label="換算先通貨"><input required pattern="[A-Z]{3}" maxLength={3} value={quote} onChange={(event) => setQuote(event.target.value.toUpperCase())} className={inputClass} /></Field>
                <Field label="レート"><input required type="number" min="0" step="any" value={rate} onChange={(event) => setRate(event.target.value)} className={inputClass} /></Field>
                <Field label="基準日"><input required type="date" value={date} onChange={(event) => setDate(event.target.value)} className={inputClass} /></Field>
                <button type="submit" disabled={disabled || base === quote || Number(rate) <= 0} className={primaryClass}>{mutation.busy ? '処理中…' : '登録'}</button>
            </fieldset>
            {base === quote && <p className="text-xs text-[var(--studio-warning)]">基準通貨と換算先通貨は別の通貨を指定してください。</p>}
        </form>
        {resource.data && <DataTable columns={['基準通貨', '換算先通貨', 'レート', '基準日', '取得元', '操作']}>
            {resource.data.length ? [...resource.data].sort((a, b) => b.as_of_date.localeCompare(a.as_of_date) || b.id - a.id).map((row) => <tr key={row.id}>
                <th scope="row" className="px-5 py-3 font-medium">{row.base_currency}</th><td className="px-5 py-3">{row.quote_currency}</td><td className="px-5 py-3 tabular-nums">{row.rate}</td><td className="whitespace-nowrap px-5 py-3">{row.as_of_date}</td><td className="px-5 py-3">{row.source === 'manual' ? '手動' : row.source}</td><td className="px-5 py-3"><button type="button" disabled={disabled} onClick={() => remove(row)} aria-label={`${row.base_currency}から${row.quote_currency}の${row.as_of_date}のレートを削除`} className={`${buttonClass} text-[var(--studio-danger)]`}>削除</button></td>
            </tr>) : <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">登録された為替レートはありません。</td></tr>}
        </DataTable>}
    </section>;
}

export default function Fx() {
    const { clientId, currentClient } = useClient();
    return <FxForClient key={clientId} currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
