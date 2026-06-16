export default function ProgressBar({ progress }) {
  return (
    <div className="bg-gray-200 h-4 rounded">
      <div className="bg-blue-500 h-4" style={{ width: `${progress}%` }} />
    </div>
  );
}