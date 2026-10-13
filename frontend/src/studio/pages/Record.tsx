import { useClient } from '../../context/ClientContext';
import RecordForm from './RecordForm';

export default function Record() {
    const { clientId } = useClient();
    return <RecordForm key={clientId} />;
}
