import Filters from "./Filters";
import { useState } from "react";

export default function ResultsTable({ data }) {

  const [filtered, setFiltered] = useState(data || []);

  const applyFilters = (f) => {
    let r = data;

    if (f.ref) {
      r = r.filter(d =>
        JSON.stringify(d.source).toLowerCase().includes(f.ref.toLowerCase())
      );
    }

    setFiltered(r);
  };

  return (
    <div>

      <Filters onApply={applyFilters} />

      <table className="mt-4 border min-w-full">
        <thead>
          <tr>
            <th>Source</th>
            <th>Destination</th>
            <th>Score</th>
          </tr>
        </thead>

        <tbody>
          {filtered.map((r, i) => (
            <tr key={i}>
              <td><pre>{JSON.stringify(r.source,null,2)}</pre></td>
              <td><pre>{JSON.stringify(r.dest,null,2)}</pre></td>
              <td>{r.score}</td>
            </tr>
          ))}
        </tbody>
      </table>

    </div>
  );
}