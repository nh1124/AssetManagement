import React, { createContext, useContext, useState, useEffect } from 'react';
import { getClients } from '../api';
import { useAuth } from './AuthContext';

interface Client {
    id: number;
    name: string;
    ai_config: Record<string, any>;
    general_settings: Record<string, any>;
    has_key: boolean;
}


interface ClientContextType {
    clientId: number;
    setClientId: (id: number) => void;
    clients: Client[];
    currentClient?: Client;
    refreshClients: () => Promise<void>;
}

const ClientContext = createContext<ClientContextType | undefined>(undefined);

export const ClientProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const { user } = useAuth();
    const [clientId, setClientIdState] = useState<number>(() => {
        const saved = Number(localStorage.getItem('finance_client_id'));
        return user?.id ?? (Number.isFinite(saved) && saved > 0 ? saved : 1);
    });
    const [clients, setClients] = useState<Client[]>([]);

    const setClientId = (id: number) => {
        if (user && id !== user.id) {
            console.warn('Client switching is disabled. Sign out and sign in as another user.');
            return;
        }
        setClientIdState(id);
        localStorage.setItem('finance_client_id', id.toString());
    };

    const refreshClients = async () => {
        try {
            const data = await getClients();
            setClients(data);
            if (data[0]?.id) {
                setClientIdState(data[0].id);
                localStorage.setItem('finance_client_id', data[0].id.toString());
            }
        } catch (error) {
            console.error('Failed to fetch clients:', error);
        }
    };

    useEffect(() => {
        refreshClients();
    }, [user?.id]);

    useEffect(() => {
        if (!user?.id) return;
        setClientIdState(user.id);
        localStorage.setItem('finance_client_id', user.id.toString());
    }, [user?.id]);

    const currentClient = clients.find((client) => client.id === clientId) || clients[0];

    return (
        <ClientContext.Provider value={{ clientId, setClientId, clients, currentClient, refreshClients }}>
            {children}
        </ClientContext.Provider>
    );
};

export const useClient = () => {
    const context = useContext(ClientContext);
    if (context === undefined) {
        throw new Error('useClient must be used within a ClientProvider');
    }
    return context;
};
