import { useState } from 'react';
import { tr } from '../i18n';
import { buttonClass, primaryClass } from './controlStyles';

/** Keep access to the codes until the user confirms they have saved them. */
export default function RecoveryCodes({ codes, onContinue, continueLabel }: { codes: string[]; onContinue: () => void; continueLabel?: string }) {
    const [saved, setSaved] = useState(false);
    const [copyStatus, setCopyStatus] = useState<'copied' | 'failed' | null>(null);
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(codes.join('\n'));
            setCopyStatus('copied');
        } catch { setCopyStatus('failed'); }
    };
    const download = () => {
        const url = URL.createObjectURL(new Blob([codes.join('\n') + '\n'], { type: 'text/plain;charset=utf-8' }));
        const link = document.createElement('a');
        link.href = url;
        link.download = 'asset-management-recovery-codes.txt';
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    return <div className="space-y-4 rounded-md border border-[var(--studio-border)] bg-[var(--studio-accent-soft)] p-4">
        <h2 className="text-sm font-semibold">{tr('回復コード', 'Recovery codes')}</h2>
        <p role="alert" className="text-sm">{tr('この画面を閉じると再表示できません。安全な場所に保存してください。', 'You cannot view these codes again after closing this screen. Save them somewhere safe.')}</p>
        <ul className="grid grid-cols-2 gap-2">{codes.map((code) => <li key={code}><code className="select-all font-mono text-sm">{code}</code></li>)}</ul>
        <div className="flex flex-wrap gap-3">
            <button type="button" onClick={() => void copy()} className={buttonClass}>{tr('すべてコピー', 'Copy all')}</button>
            <button type="button" onClick={download} className={buttonClass}>{tr('テキストで保存', 'Download .txt')}</button>
        </div>
        {copyStatus && <p role={copyStatus === 'failed' ? 'alert' : 'status'} className="text-sm">{copyStatus === 'copied' ? tr('コピーしました。', 'Copied.') : tr('コピーできません。ダウンロードしてください。', 'Could not copy. Download the codes instead.')}</p>}
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={saved} onChange={(event) => setSaved(event.target.checked)} />{tr('安全な場所に保存しました', 'I have saved these codes')}</label>
        <button type="button" disabled={!saved} onClick={() => { if (saved) onContinue(); }} className={primaryClass}>{continueLabel ?? tr('完了', 'Done')}</button>
    </div>;
}
