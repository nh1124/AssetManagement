import React, { createContext, useContext, useState, useEffect } from 'react';

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
    refreshClients: () => Promise<void>;
}

const ClientContext = createContext<ClientContextType | undefined>(undefined);

export const ClientProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    // Default to client 1 (Default User)
    const [clientId, setClientIdState] = useState<number>(() => {
        const saved = localStorage.getItem('finance_client_id');
        return saved ? parseInt(saved, 10) : 1;
    });
    const [clients, setClients] = useState<Client[]>([]);

    const setClientId = (id: number) => {
        setClientIdState(id);
        localStorage.setItem('finance_client_id', id.toString());
        // Force reload or just let interceptor handle it
        window.location.reload();
    };

    const refreshClients = async () => {
        try {
            const response = await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8100'}/clients/`);
            if (response.ok) {
                const data = await response.json();
                setClients(data);
            }
        } catch (error) {
            console.error('Failed to fetch clients:', error);
        }
    };

    useEffect(() => {
        refreshClients();
    }, []);

    return (
        <ClientContext.Provider value={{ clientId, setClientId, clients, refreshClients }}>
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
