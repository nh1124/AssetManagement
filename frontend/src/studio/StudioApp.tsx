import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import StudioLayout from './components/StudioLayout';
import ScreenTabs from './components/ScreenTabs';
import Pending from './components/Pending';
import { SETTINGS_PATH, STUDIO_HOME, STUDIO_SCREENS, type StudioScreen } from './navigation';
import './theme.css';

/** What each screen will hold, so a routed-but-empty screen says which wave fills it. */
const PENDING_NOTES: Record<string, { wave: string; note: string }> = {
    ledger: { wave: 'W2', note: '記録の一覧、未照合（取引の提案）、予算との対応。' },
    assets: { wave: 'W3', note: '貸借対照表、口座（active の切り替え）、取り置き（展開で口座別の内訳）。' },
    flows: { wave: 'W2', note: '対象月の収入と支出を分類ごとに。' },
    budget: { wave: 'W4', note: '月末計画と照合済み実績の差、行動の記録。' },
    goals: { wave: 'W5', note: '資産推移、ゴール案の比較と切り替え。' },
    'db/accounts': { wave: 'W6', note: '口座と勘定科目の一覧・編集。' },
    'db/fx': { wave: 'W6', note: '為替レートの登録と自動更新。' },
    'db/definitions': { wave: 'W6', note: '継続支出・収入・返済・配分の定義（registry）。' },
    'db/fixed-assets': { wave: 'W6', note: '固定資産と更新費の積立。' },
    'db/consumables': { wave: 'W6', note: '消耗品の単価と購入周期。' },
    'automation/ai': { wave: 'W7', note: 'AI 操作の権限ルール。' },
    'automation/approvals': { wave: 'W7', note: '変更要求の承認と適用。' },
    'automation/audit': { wave: 'W7', note: 'AI 操作の監査ログ。' },
    'debug/data-health': { wave: 'W8', note: 'data_health の全件表示と修復。リリース前に削除する。' },
};

function ScreenShell({ screen }: { screen: StudioScreen }) {
    const { pathname } = useLocation();
    const pending = PENDING_NOTES[screen.path];
    const tab = screen.tabs?.find((candidate) => {
        const full = candidate.segment ? `/${screen.path}/${candidate.segment}` : `/${screen.path}`;
        return pathname.replace(/\/+$/, '') === full;
    });
    return (
        <>
            <ScreenTabs screen={screen} />
            <Pending wave={pending?.wave ?? '未割当'}>
                {pending?.note}
                {tab?.segment ? `（${tab.label}）` : null}
            </Pending>
        </>
    );
}

export default function StudioApp() {
    return (
        <BrowserRouter basename="/studio">
            <Routes>
                <Route element={<StudioLayout />}>
                    <Route index element={<Navigate to={STUDIO_HOME} replace />} />
                    {STUDIO_SCREENS.map((screen) => (
                        <Route key={screen.path} path={screen.path}>
                            <Route index element={<ScreenShell screen={screen} />} />
                            {screen.tabs
                                ?.filter((tab) => tab.segment)
                                .map((tab) => (
                                    <Route
                                        key={tab.segment}
                                        path={tab.segment}
                                        element={<ScreenShell screen={screen} />}
                                    />
                                ))}
                        </Route>
                    ))}
                    <Route
                        path={SETTINGS_PATH}
                        element={
                            <Pending wave="W6">
                                設定。クライアント、通貨、MFA、データの入出力。
                            </Pending>
                        }
                    />
                    <Route path="*" element={<Navigate to={STUDIO_HOME} replace />} />
                </Route>
            </Routes>
        </BrowserRouter>
    );
}
