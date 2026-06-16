export default function KPICards({ summary }) {
  return (
    <div className="grid grid-cols-4 gap-4">
      <div className="bg-white p-4 shadow rounded">Total: {summary.total}</div>
    </div>
  );
}