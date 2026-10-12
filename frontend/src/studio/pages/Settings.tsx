import { useState, type FormEvent } from 'react';
import { exportData, getMfaStatus, importData, updateClientSettings } from '../../api';
import { useClient } from '../../context/ClientContext';
import { useResource } from '../useResource';
import { Feedback, Field } from './db/Database';
import { buttonClass, inputClass, primaryClass, today, useMutation } from './db/forms';

function SettingsForClient() {
    const { clientId, currentClient, refreshClients } = useClient();
    const mfa = useResource(getMfaStatus);
    const mutation = useMutation();
    const [currencyEdit, setCurrencyEdit] = useState<string | null>(null);
    const [savedCurrency, setSavedCurrency] = useState<string | null>(null);
    const [file, setFile] = useState<File | null>(null);
    const general: Record<string, unknown> = currentClient?.general_settings ?? {};
    const storedCurrency = savedCurrency ?? (typeof general.currency === 'string' ? general.currency : 'JPY');
    const currency = currencyEdit ?? storedCurrency;
    const identified = currentClient?.id === clientId;
    const disabled = mutation.busy || !identified;
    const save = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (disabled || currency === storedCurrency) return;
        // Preserve unrelated preferences because settings are replaced as one object.
        void mutation.run(() => updateClientSettings(clientId, { ...general, currency }), '通貨を保存しました。', () => {
            setSavedCurrency(currency);
            setCurrencyEdit(null);
            void refreshClients();
        });
    };
    const download = () => {
        if (disabled) return;
        void mutation.run(async () => {
            const snapshot: unknown = await exportData();
            const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' }));
            const link = document.createElement('a');
            link.href = url;
            link.download = `asset-management-client-${clientId}-${today()}.json`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            // Give the browser time to start the download before releasing its object URL.
            window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        }, 'データのダウンロードを開始しました。');
    };
    const upload = () => {
        if (disabled || !file) return;
        if (!window.confirm(`「${file.name}」を読み込みますか？\n「${currentClient?.name}」（クライアント #${clientId}）の既存データをすべて置き換えます。`)) return;
        void mutation.run(async () => {
            let payload: unknown;
            try { payload = JSON.parse(await file.text()); }
            catch { throw new Error('JSONファイルを読み込めませんでした。ファイルの内容を確認してください。'); }
            if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) throw new Error('データのバックアップを含むJSONファイルを選択してください。');
            await importData(payload);
        }, 'データを読み込みました。', () => {
            setFile(null);
            setCurrencyEdit(null);
            setSavedCurrency(null);
            void refreshClients();
            mfa.reload();
        });
    };
    return <section className="space-y-6">
        <div><h2 className="text-lg font-semibold">設定</h2><p className="mt-1 text-xs text-[var(--studio-text-muted)]">{identified ? `クライアント：${currentClient.name}（#${clientId}）` : 'クライアントを確認しています…'}</p></div>
        <Feedback error={mutation.error} message={mutation.message} />
        <form onSubmit={save} className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <h3 className="text-sm font-semibold">クライアントと表示通貨</h3>
            <fieldset disabled={disabled} className="flex flex-wrap items-end gap-4">
                <Field label="通貨"><input required pattern="[A-Z]{3}" maxLength={3} value={currency} onChange={(event) => setCurrencyEdit(event.target.value.toUpperCase())} className={inputClass} list="studio-settings-currencies" /><datalist id="studio-settings-currencies">{['JPY', 'USD', 'EUR', 'GBP', 'CNY', 'KRW'].map((code) => <option key={code} value={code} />)}</datalist></Field>
                <button type="submit" disabled={disabled || currency === storedCurrency} className={primaryClass}>{mutation.busy ? '処理中…' : '通貨を保存'}</button>
            </fieldset>
        </form>
        <section className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <div className="flex items-center justify-between gap-3"><h3 className="text-sm font-semibold">多要素認証（MFA）</h3><button type="button" disabled={mfa.loading || mutation.busy} onClick={mfa.reload} className={buttonClass}>再読み込み</button></div>
            <Feedback loading={mfa.loading} error={mfa.error} />
            {mfa.data && <dl className="space-y-2 text-sm"><div className="flex gap-3"><dt className="text-[var(--studio-text-muted)]">状態</dt><dd>{mfa.data.enabled ? '有効' : '無効'}</dd></div>{mfa.data.enabled && <><div className="flex gap-3"><dt className="text-[var(--studio-text-muted)]">リカバリーコード残数</dt><dd>{mfa.data.recovery_codes_remaining}件</dd></div>{mfa.data.enabled_at && <div className="flex gap-3"><dt className="text-[var(--studio-text-muted)]">有効化日時</dt><dd>{new Date(mfa.data.enabled_at).toLocaleString('ja-JP')}</dd></div>}{mfa.data.last_verified_at && <div className="flex gap-3"><dt className="text-[var(--studio-text-muted)]">最終認証日時</dt><dd>{new Date(mfa.data.last_verified_at).toLocaleString('ja-JP')}</dd></div>}</>}</dl>}
            <p className="text-xs text-[var(--studio-text-muted)]">MFAの設定・解除・リカバリーコードの管理は、従来の画面の「設定」で行います。<a href="/" className="ml-2 underline text-[var(--studio-accent)]">従来の画面を開く</a></p>
        </section>
        <section className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <h3 className="text-sm font-semibold">データの入出力</h3>
            <button type="button" disabled={disabled} onClick={download} className={buttonClass}>データを書き出す（JSON）</button>
            <div className="space-y-3 border-t border-[var(--studio-border)] pt-4">
                <Field label="読み込むバックアップファイル"><input type="file" accept=".json,application/json" disabled={disabled} onChange={(event) => { setFile(event.target.files?.[0] ?? null); event.target.value = ''; }} className={inputClass} /></Field>
                {file && <p className="text-sm">選択したファイル：{file.name}</p>}
                <p className="text-xs text-[var(--studio-text-muted)]">読み込みは、このクライアントの既存データをすべて置き換えます。</p>
                <button type="button" disabled={disabled || !file} onClick={upload} className={buttonClass}>{mutation.busy ? '処理中…' : 'データを読み込む'}</button>
            </div>
        </section>
    </section>;
}

export default function Settings() {
    const { clientId } = useClient();
    // Switching clients discards selected files and unfinished settings edits.
    return <SettingsForClient key={clientId} />;
}
