export function currentMonth(): string {
    // Local dates keep the initial month correct near a UTC month boundary.
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

export function monthRange(month: string): { startDate: string; endDate: string } {
    const [year, number] = month.split('-').map(Number);
    const lastDay = new Date(year, number, 0).getDate();
    return { startDate: `${month}-01`, endDate: `${month}-${String(lastDay).padStart(2, '0')}` };
}
