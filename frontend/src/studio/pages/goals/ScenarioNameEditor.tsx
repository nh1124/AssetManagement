import { useId, useState } from 'react';
import { EditorActions, Field } from '../db/Database';
import { inputClass } from '../db/forms';
import { tr } from '../../i18n';

export default function ScenarioNameEditor({ initialName, busy, onSave, onCancel }: {
    initialName: string; busy: boolean; onSave: (name: string) => void; onCancel: () => void;
}) {
    const form = useId();
    const [name, setName] = useState(initialName);
    return <form id={form} onSubmit={(event) => {
        event.preventDefault();
        if (!busy && name.trim()) onSave(name.trim());
    }}>
        <Field label={tr('名前', 'Name')}><input required autoFocus value={name} disabled={busy} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
        <EditorActions form={form} busy={busy || !name.trim()} onCancel={onCancel} />
    </form>;
}
