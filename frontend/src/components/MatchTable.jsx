import { useState } from "react";

export default function MatchTable({ data }) {

  const [selected, setSelected] = useState(null);

  return (
    <div className="bg-white rounded-xl shadow p-4">

      <h3 className="font-bold mb-3">Matches</h3>

      <table className="w-full text-sm">

        <thead className="bg-gray-100">
          <tr>
            <th>Layer</th>
            <th>Src Amount</th>
            <th>Dest Amount</th>
            <th>Confidence</th>
          </tr>
        </thead>

        <tbody>
          {data && data.slice(0, 50).map((r, i) => (
            <tr
              key={i}
              className="border-b hover:bg-gray-50 cursor-pointer"
              onClick={() => setSelected(r)}
            >
              <td>{r.layer}</td>
              <td>{r.src_amount}</td>
              <td>{r.dest_amount}</td>

              <td className={
                r.confidence_score > 0.9
                  ? "text-green-600"
                  : r.confidence_score > 0.7
                  ? "text-yellow-600"
                  : "text-red-600"
              }>
                {r.confidence_score}
              </td>

            </tr>
          ))}
        </tbody>

      </table>

      {selected && (
        <div className="mt-4 p-3 bg-gray-50 border rounded">
          <h4 className="font-semibold">Details</h4>
          <pre className="text-xs">
            {JSON.stringify(selected, null, 2)}
          </pre>
        </div>
      )}

    </div>
  );
}