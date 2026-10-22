import { useState } from 'react';
import Overlay from '../studio/components/Overlay';
import { tr } from '../studio/i18n';
import type { AdminApi } from './api';
import { Field, Notice, SaveButton } from './ui';
import { useAction } from './hooks';

export default function StepUp({ api, onSuccess, onCancel }: { api: AdminApi; onSuccess: () => void; onCancel: () => void }) {
    const [code, setCode] = useState('');
    const action = useAction();
    return <Overlay title={tr('再認証', 'Verify your identity')} onClose={onCancel} busy={action.busy}>
        <p className="admin-warning" role="status">{tr('認証後に、選んだ操作を続けます。', 'Your selected action will continue after verification.')}</p>
        <form onSubmit={event => {
            event.preventDefault();
            void action.run(async () => {
                await api.request('/session/step-up', { method: 'POST', body: { code: code.trim() }, retry: false });
                onSuccess();
            }, '');
        }}><fieldset disabled={action.busy}>
            <Field autoFocus label={tr('認証コード', 'Authentication code')} required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" value={code} onChange={e => setCode(e.target.value)} />
            <Notice error={action.error} /><SaveButton busy={action.busy} label={tr('認証して続ける', 'Verify and continue')} />
        </fieldset></form>
    </Overlay>;
}
