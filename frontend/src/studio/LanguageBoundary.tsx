import { Fragment, useEffect, type ReactNode } from 'react';
import { useClient } from '../context/ClientContext';
import { activeLanguage, LANGUAGE_STORAGE_KEY, setActiveLanguage, type Language } from './i18n';

/** Applies the client's language to everything inside; a change remounts the subtree in the new language. */
export default function LanguageBoundary({ children }: { children: ReactNode }) {
    const { clientId, currentClient } = useClient();
    // Until the client loads, keep the last known language so an English UI does not flash Japanese.
    const language: Language = currentClient?.id === clientId
        ? currentClient.general_settings?.language === 'en' ? 'en' : 'ja'
        : activeLanguage();
    setActiveLanguage(language);
    useEffect(() => {
        document.documentElement.lang = language;
        try {
            localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
        } catch {
            // The next sign-in page falls back to Japanese.
        }
    }, [language]);
    return <Fragment key={language}>{children}</Fragment>;
}
