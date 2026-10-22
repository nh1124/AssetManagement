import { useCallback, useState } from 'react';
import QRCode from 'qrcode';
import type { TotpProvisioning } from '../../types';
import { tr } from '../i18n';
import { useResource } from '../useResource';
import { buttonClass } from './controlStyles';

export default function TotpSetup({ setup }: { setup: TotpProvisioning }) {
    const load = useCallback(() => QRCode.toDataURL(setup.otpauth_uri, { width: 208, margin: 2, errorCorrectionLevel: 'M' }), [setup.otpauth_uri]);
    const qr = useResource(load);
    const [copyStatus, setCopyStatus] = useState<'copied' | 'failed' | null>(null);
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(setup.manual_entry_key);
            setCopyStatus('copied');
        } catch { setCopyStatus('failed'); }
    };
    return <div className="space-y-3">
        {qr.data ? <img src={qr.data} alt={tr('認証アプリ設定用のQRコード', 'QR code for your authenticator app')} width={208} height={208} className="mx-auto" />
            : <p role={qr.error ? 'alert' : 'status'} className="text-sm">{qr.error ? tr('QRコードを表示できません。下のキーを入力してください。', 'Could not display the QR code. Enter the key below.') : tr('QRコードを準備中…', 'Preparing QR code…')}</p>}
        <div className="space-y-2 text-sm">
            <p className="text-[var(--studio-text-muted)]">{tr('手入力用のキー', 'Manual entry key')}</p>
            <code className="block select-all break-all font-mono">{setup.manual_entry_key}</code>
            <button type="button" onClick={() => void copy()} className={buttonClass}>{tr('キーをコピー', 'Copy key')}</button>
            {copyStatus && <p role={copyStatus === 'failed' ? 'alert' : 'status'}>{copyStatus === 'copied' ? tr('コピーしました。', 'Copied.') : tr('コピーできません。キーを選んで保存してください。', 'Could not copy. Select and save the key.')}</p>}
        </div>
    </div>;
}
