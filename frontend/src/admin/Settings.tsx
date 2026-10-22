import { useState } from 'react';
import { tr } from '../studio/i18n';
import { Help } from '../studio/components/Help';
import { useAdmin } from './context';
import { useAction, useQuery } from './hooks';
import { date } from './format';
import { Field, Loading, Notice, Page, SaveButton } from './ui';
import type { Setting } from './types';

const bounds: Record<string, [number, number]> = { account_deletion_grace_days: [1, 365], login_lockout_threshold: [3, 20], login_lockout_minutes: [1, 1440] };
function settingLabel(key: string) {
    const labels: Record<string, string> = { registration_mode: tr('新規登録', 'Registration'), account_deletion_grace_days: tr('削除までの日数', 'Deletion grace days'), login_lockout_threshold: tr('ロックまでの失敗回数', 'Failed attempts before lockout'), login_lockout_minutes: tr('ロックする時間（分）', 'Lockout duration (minutes)') };
    return labels[key] ?? key;
}
function modeLabel(value: string) { return value === 'open' ? tr('誰でも登録できる', 'Anyone can sign up') : value === 'approval' ? tr('承認制', 'Approval required') : value === 'closed' ? tr('管理者が作るだけ', 'Administrators create accounts') : value; }
function SettingEditor({ settingKey, setting, onSaved }: { settingKey: string; setting: Setting; onSaved: () => void }) {
    const { api, can } = useAdmin();
    const [value, setValue] = useState(String(setting.value));
    const action = useAction();
    const registration = settingKey === 'registration_mode';
    const label = settingLabel(settingKey);
    return <section className="admin-card"><h2>{label}</h2>
        <dl className="admin-attributes">
            <div><dt>{tr('現在の値', 'Current value')}</dt><dd>{registration ? modeLabel(String(setting.value)) : setting.value}</dd></div>
            <div><dt>{tr('既定値', 'Default')}</dt><dd>{registration ? modeLabel(String(setting.default)) : setting.default}</dd></div>
            <div><dt>{tr('更新日時', 'Updated at')}</dt><dd>{date(setting.updated_at)}</dd></div>
            <div><dt>{tr('更新者', 'Updated by')}</dt><dd>{setting.updated_by || tr('—', '—')}</dd></div>
        </dl>
        {can('settings.manage') && <form onSubmit={e => { e.preventDefault(); void action.run(async () => {
            await api.put(`/settings/${encodeURIComponent(settingKey)}`, { value: registration ? value : Number(value) }); onSaved();
        }, tr('保存しました。', 'Saved.')); }}><fieldset disabled={action.busy}>
            {registration ? <fieldset><legend>{label}</legend>{[
                ['open', modeLabel('open'), tr('ログイン画面から誰でもアカウントを作れます。', 'Anyone can create an account from the sign-in page.')],
                ['approval', modeLabel('approval'), tr('登録はできますが、管理者が承認するまで使えません。', 'Accounts can be created but cannot be used until an administrator approves them.')],
                ['closed', modeLabel('closed'), tr('ログイン画面の登録を止め、管理者だけがアカウントを作ります。', 'Sign-up is closed; only administrators create accounts.')],
            ].map(([mode, title, help]) => <div className="admin-radio" key={mode}><input id={`registration-${mode}`} type="radio" name="registration-mode" value={mode} checked={value === mode} onChange={() => setValue(mode)} /><label htmlFor={`registration-${mode}`}>{title}</label><Help label={title} text={help} /></div>)}</fieldset>
                : <Field label={label} type="number" min={bounds[settingKey]?.[0]} max={bounds[settingKey]?.[1]} step={1} required value={value} onChange={e => setValue(e.target.value)} help={`${tr('範囲', 'Range')}: ${bounds[settingKey]?.[0]}–${bounds[settingKey]?.[1]}`} />}
            <Notice {...action} /><SaveButton busy={action.busy} />
        </fieldset></form>}
    </section>;
}
export default function Settings() {
    const query = useQuery<Record<string, Setting>>('/settings');
    const [message, setMessage] = useState('');
    return <Page title={tr('システム設定', 'System settings')} help={tr('この仕組み全体に適用します。保存時に認証コードを求めることがあります。', 'These settings apply across this installation. Saving may require an authentication code.')}>
        <Notice error={query.error} message={message} />{query.error && <button onClick={query.reload}>{tr('再読み込み', 'Reload')}</button>}{query.loading && <Loading />}
        {query.data && Object.entries(query.data).map(([key, setting]) => <SettingEditor key={`${key}-${setting.updated_at ?? ''}`} settingKey={key} setting={setting} onSaved={() => { setMessage(tr('保存しました。', 'Saved.')); query.reload(); }} />)}
    </Page>;
}
