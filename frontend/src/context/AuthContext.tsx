import React, { createContext, useContext, useState, useEffect } from 'react';
import { login as apiLogin, register as apiRegister, getMe } from '../api';

interface User {
    id: number;
    name: string;
    username: string;
    email?: string;
}

interface AuthContextType {
    user: User | null;
    isAuthenticated: boolean;
    login: (credentials: any) => Promise<void>;
    register: (userData: any) => Promise<void>;
    logout: () => void;
    isLoading: boolean;
}


const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<User | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    const checkAuth = async () => {
        const token = localStorage.getItem('finance_access_token');
        if (token) {
            try {
                const userData = await getMe();
                setUser(userData);
            } catch (error) {
                console.error('Session expired');
                logout();
            }
        }
        setIsLoading(false);
    };

    useEffect(() => {
        checkAuth();
    }, []);

    const login = async (credentials: any) => {
        const data = await apiLogin(credentials);
        localStorage.setItem('finance_access_token', data.access_token);
        localStorage.setItem('finance_client_id', data.client_id.toString());
        setUser({
            id: data.client_id,
            name: data.name,
            username: credentials.username
        });
    };

    const register = async (userData: any) => {
        await apiRegister(userData);
        // Automatically login after registration
        await login({ username: userData.username, password: userData.password });
    };


    const logout = () => {
        localStorage.removeItem('finance_access_token');
        localStorage.removeItem('finance_client_id');
        setUser(null);
    };

    return (
        <AuthContext.Provider value={{ user, isAuthenticated: !!user, login, register, logout, isLoading }}>
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
