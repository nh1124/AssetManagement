import { createContext, useContext } from 'react';
import type { AdminApi } from './api';
import type { Me } from './types';
export const AdminContext = createContext<{ api: AdminApi; me: Me; refreshMe: () => Promise<void> } | null>(null);
export function useAdmin() {
    const context = useContext(AdminContext);
    if (!context) throw new Error('AdminContext missing');
    return { ...context, can: (permission: string) => context.me.permissions.includes(permission) };
}
