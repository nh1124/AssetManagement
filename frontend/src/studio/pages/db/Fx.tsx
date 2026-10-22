import Overlay, { OverlayFooter } from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useId, useState, type FormEvent } from 'react';
import { autoUpdateExchangeRates, trackCurrency, untrackCurrency, deleteExchangeRate, getExchangeRates, getTrackedCurrencies } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { ExchangeRate } from '../../../types';
import { useResource } from '../../useResource';
import { DataTable, EditableRow, RowTitle, Feedback, Field } from './Database';
import { buttonClass, inputClass, primaryClass, useMutation } from './forms';
import { currencyHistory } from './fxHistory';
import { tr } from '../../i18n';

const loadFx = async () => {
    const [tracked, rates] = await Promise.all([getTrackedCurrencies(), getExchangeRates()]);
    return { tracked, rates };
};

function FxForClient({ currency }: { currency: string }) {
    const formId = useId();
    const confirm = useConfirm();
    const resource = useResource(loadFx);
    const mutation = useMutation();
    const [adding, setAdding] = useState(false);
    const [code, setCode] = useState('');
    const [selected, setSelected] = useState<string | null>(null);
    const disabled = mutation.busy || resource.loading || Boolean(resource.error);
    const add = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (disabled || !/^[A-Z]{3}$/.test(code)) return;
        void mutation.run(() => trackCurrency(code), tr('追跡通貨を追加しました。', 'Currency added.'), () => { setAdding(false); setCode(''); resource.reload(); });
    };
    const stop = async () => {
        if (disabled || !selected || !(await confirm(tr(`${selected} の追跡をやめますか？取得済みのレートは残ります。`, `Stop tracking ${selected}? Rates already fetched are kept.`), tr('追跡をやめる', 'Stop tracking')))) return;
        void mutation.run(() => untrackCurrency(selected), tr('追跡をやめました。', 'Stopped tracking.'), () => { setSelected(null); resource.reload(); });
    };
    const remove = async (row: ExchangeRate) => {
        if (disabled || !(await confirm(tr(`${row.as_of_date} のレートを削除しますか？`, `Delete the rate of ${row.as_of_date}?`), tr('削除する', 'Delete')))) return;
        void mutation.run(() => deleteExchangeRate(row.id), tr('レートを削除しました。', 'Rate deleted.'), resource.reload);
    };
    const refresh = () => void mutation.run(async () => {
        const result = await autoUpdateExchangeRates();
        resource.reload();
        if (result.errors.length) throw new Error(result.errors.map((row) => `${row.base_currency}${tr('：', ': ')}${row.error}`).join(tr('／', ' / ')));
    }, tr('為替レートを更新しました。', 'Exchange rates updated.'));
    const history = selected && resource.data ? currencyHistory(resource.data.rates, selected, currency) : [];
    return <section className="space-y-4">
        <div className="flex gap-2"><button type="button" disabled={disabled || adding} onClick={() => setAdding(true)} className={buttonClass}>{tr('新規作成', 'New')}</button><button type="button" disabled={disabled} onClick={refresh} className={buttonClass}>{tr('更新', 'Update')}</button></div>
        <Feedback loading={resource.loading} error={mutation.error || resource.error} message={mutation.message} />
        {adding && <Overlay title={tr('追跡通貨の新規作成', 'Track a currency')} onClose={() => setAdding(false)}><Feedback error={mutation.error} /><form id={formId} onSubmit={add}>
            <Field label={tr('通貨', 'Currency')} help={tr(`3文字で指定。${currency} へのレートを取得します。`, `A three-letter code. Rates to ${currency} are fetched.`)}><input required pattern="[A-Z]{3}" maxLength={3} value={code} disabled={disabled} onChange={(event) => setCode(event.target.value.toUpperCase())} className={inputClass} /></Field>
            <OverlayFooter><button type="submit" form={formId} disabled={disabled || code === currency} className={primaryClass}>{tr('追加', 'Add')}</button></OverlayFooter>
        </form></Overlay>}
        {selected && <Overlay title={tr(`${selected} のレート履歴（→ ${currency}）`, `${selected} rate history (to ${currency})`)} onClose={() => setSelected(null)}>
            <Feedback error={mutation.error} />
            <DataTable columns={[tr('レート', 'Rate'), tr('基準日', 'As of'), tr('取得元', 'Source')]}>
                {history.map((row) => <tr key={row.id}><td className="px-5 py-3 tabular-nums">{row.rate}</td><td className="px-5 py-3">{row.as_of_date}</td><td className="px-5 py-3">{row.source}<button type="button" disabled={disabled} onClick={() => void remove(row)} className={`${buttonClass} ml-3 text-[var(--studio-danger)]`}>{tr('削除', 'Delete')}</button></td></tr>)}
                {!history.length && <tr><td colSpan={3} className="px-5 py-4">{tr('履歴はありません。', 'No history.')}</td></tr>}
            </DataTable>
            <OverlayFooter><div className="mr-auto"><button type="button" disabled={disabled} onClick={() => void stop()} className={`${buttonClass} text-[var(--studio-danger)]`}>{tr('追跡をやめる', 'Stop tracking')}</button></div></OverlayFooter>
        </Overlay>}
        {resource.data && <DataTable columns={[tr('通貨', 'Currency'), tr('最新レート', 'Latest rate'), tr('基準日', 'As of'), tr('取得元', 'Source')]}>
            {resource.data.tracked.map((row) => {
                const latest = currencyHistory(resource.data?.rates ?? [], row.currency, currency)[0];
                const open = () => setSelected(row.currency);
                return <EditableRow key={row.currency} disabled={disabled} onEdit={open}><RowTitle name={row.currency} disabled={disabled} onEdit={open}>{row.currency}</RowTitle><td className="px-5 py-3 tabular-nums">{latest?.rate ?? '—'}</td><td className="px-5 py-3">{latest?.as_of_date ?? '—'}</td><td className="px-5 py-3">{latest?.source ?? '—'}</td></EditableRow>;
            })}
            {!resource.data.tracked.length && <tr><td colSpan={4} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('追跡中の通貨はありません。', 'No currencies tracked.')}</td></tr>}
        </DataTable>}
    </section>;
}

export default function Fx() {
    const { clientId, currentClient } = useClient();
    return <FxForClient key={clientId} currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
