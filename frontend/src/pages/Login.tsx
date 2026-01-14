import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { LogIn, User, Lock, AlertCircle } from 'lucide-react';

export default function LoginPage() {
    const [mode, setMode] = useState<'login' | 'register'>('login');
    const [username, setUsername] = useState('admin');
    const [password, setPassword] = useState('adminadmin');
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const { login, register } = useAuth();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setIsLoading(true);
        try {
            if (mode === 'login') {
                await login({ username, password });
            } else {
                await register({ name, username, password, email: email || undefined });
            }
        } catch (err: any) {
            setError(err.response?.data?.detail || (mode === 'login' ? 'Login failed' : 'Registration failed'));
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
            <div className="w-full max-w-md">
                <div className="text-center mb-8">
                    <h1 className="text-2xl font-bold text-white mb-2">Finance IDE</h1>
                    <p className="text-slate-400 text-sm">
                        {mode === 'login' ? 'Sign in to manage your assets' : 'Create a new account to get started'}
                    </p>
                </div>

                <form onSubmit={handleSubmit} className="bg-slate-900 border border-slate-800 p-8 shadow-2xl rounded-sm">
                    {error && (
                        <div className="mb-6 p-3 bg-red-950/30 border border-red-900/50 text-red-500 text-xs flex items-center gap-2 animate-in fade-in slide-in-from-top-1">
                            <AlertCircle size={14} />
                            {error}
                        </div>
                    )}

                    <div className="space-y-4">
                        {mode === 'register' && (
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">Company/Full Name</label>
                                <div className="relative">
                                    <User className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" size={16} />
                                    <input
                                        type="text"
                                        value={name}
                                        onChange={(e) => setName(e.target.value)}
                                        className="w-full bg-slate-800/50 border border-slate-700 pl-10 pr-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500 transition-all placeholder:text-slate-600"
                                        placeholder="Tenant Name"
                                        required
                                    />
                                </div>
                            </div>
                        )}

                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">Username</label>
                            <div className="relative">
                                <User className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" size={16} />
                                <input
                                    type="text"
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                    className="w-full bg-slate-800/50 border border-slate-700 pl-10 pr-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500 transition-all placeholder:text-slate-600"
                                    placeholder="Enter username"
                                    required
                                />
                            </div>
                        </div>

                        {mode === 'register' && (
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">Email (Optional)</label>
                                <div className="relative">
                                    <AlertCircle className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" size={16} />
                                    <input
                                        type="email"
                                        value={email}
                                        onChange={(e) => setEmail(e.target.value)}
                                        className="w-full bg-slate-800/50 border border-slate-700 pl-10 pr-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500 transition-all placeholder:text-slate-600"
                                        placeholder="name@example.com"
                                    />
                                </div>
                            </div>
                        )}

                        <div>
                            <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">Password</label>
                            <div className="relative">
                                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" size={16} />
                                <input
                                    type="password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    className="w-full bg-slate-800/50 border border-slate-700 pl-10 pr-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500 transition-all placeholder:text-slate-600"
                                    placeholder="Enter password"
                                    required
                                    minLength={8}
                                />
                            </div>
                        </div>

                        <button
                            type="submit"
                            disabled={isLoading}
                            className="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-medium py-2.5 flex items-center justify-center gap-2 transition-all disabled:opacity-50 disabled:cursor-not-allowed mt-6 active:scale-[0.98]"
                        >
                            {isLoading ? (
                                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                            ) : (
                                mode === 'login' ? <LogIn size={18} /> : <User size={18} />
                            )}
                            {isLoading ? (mode === 'login' ? 'Signing in...' : 'Creating Account...') : (mode === 'login' ? 'Sign In' : 'Sign Up')}
                        </button>
                    </div>

                    <div className="mt-8 pt-6 border-t border-slate-800 text-center">
                        <p className="text-xs text-slate-500">
                            {mode === 'login' ? "Don't have an account?" : "Already have an account?"}{' '}
                            <button
                                type="button"
                                onClick={() => {
                                    setMode(mode === 'login' ? 'register' : 'login');
                                    setError('');
                                }}
                                className="text-emerald-500 hover:text-emerald-400 font-medium transition-colors"
                            >
                                {mode === 'login' ? 'Sign Up' : 'Sign In'}
                            </button>
                        </p>

                        {mode === 'login' && (
                            <p className="text-[10px] text-slate-700 mt-4 italic">
                                Dev Access: <code className="text-slate-600 bg-slate-950 px-1">admin / adminadmin</code>
                            </p>
                        )}
                    </div>
                </form>
            </div>
        </div>
    );
}

