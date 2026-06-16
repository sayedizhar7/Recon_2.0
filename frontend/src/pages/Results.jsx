import { useEffect, useState } from "react";
import axios from "axios";
import ResultsTable from "../components/ResultsTable";

const BASE = "http://localhost:8000";

export default function Results({ runId }) {

  const [data, setData] = useState([]);
  const [layer, setLayer] = useState("Layer1");

  useEffect(() => {
    fetch();
  }, []);

  const fetch = async () => {
    const res = await axios.get(`${BASE}/results/${runId}`);
    setData(res.data.data);
  };

  return (
    <div>

      <h2 className="text-xl font-bold">Run {runId}</h2>

      <div className="flex gap-2 mt-3">
        {["Layer0","Layer1","Layer2","Layer3","Layer4","Layer5"].map(l => (
          <button
            key={l}
            onClick={() => setLayer(l)}
            className="px-2 py-1 bg-gray-200 rounded"
          >
            {l}
          </button>
        ))}
      </div>

      <ResultsTable data={data.filter(d => d.layer === layer)} />

    </div>
  );
}