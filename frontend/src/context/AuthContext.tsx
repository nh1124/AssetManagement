import React, { createContext, useContext, useState, useEffect } from 'react';
import { login as apiLogin, register as apiRegister, getMe } from '../api';

interface User {
    id: number;
    name: string;
    username: string;
    email?: string;
    general_settings?: Record<string, unknown>;
}

interface AuthContextType {
    user: User | null;
    isAuthenticated: boolean;
    login: typeof apiLogin;
    register: typeof apiRegister;
    completeSignIn: (accessToken: string, client: Pick<User, 'id' | 'name' | 'username'>) => void;
    logout: () => void;
    isLoading: boolean;
}


const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<User | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        let active = true;
        const checkAuth = async () => {
            try {
                const userData = localStorage.getItem('finance_access_token') ? await getMe() : null;
                if (active) setUser(userData);
            } catch {
                if (active) {
                    localStorage.removeItem('finance_access_token');
                    localStorage.removeItem('finance_client_id');
                    setUser(null);
                }
            } finally {
                if (active) setIsLoading(false);
            }
        };
        void checkAuth();
        return () => { active = false; };
    }, []);

    const completeSignIn: AuthContextType['completeSignIn'] = (accessToken, client) => {
        localStorage.setItem('finance_access_token', accessToken);
        localStorage.setItem('finance_client_id', client.id.toString());
        setUser(client);
    };


    const logout = () => {
        localStorage.removeItem('finance_access_token');
        localStorage.removeItem('finance_client_id');
        setUser(null);
    };

    return (
        <AuthContext.Provider value={{ user, isAuthenticated: !!user, login: apiLogin, register: apiRegister, completeSignIn, logout, isLoading }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (context === undefined) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
};
