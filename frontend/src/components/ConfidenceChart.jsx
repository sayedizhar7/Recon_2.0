import { PieChart, Pie, Cell } from "recharts";

export default function ConfidenceChart({data}){

  const chart = [
    {name:"High",value:10},
    {name:"Medium",value:5},
    {name:"Low",value:2},
  ];

  return(
    <PieChart width={300} height={300}>
      <Pie data={chart} dataKey="value">
        <Cell fill="#22c55e"/>
        <Cell fill="#facc15"/>
        <Cell fill="#ef4444"/>
      </Pie>
    </PieChart>
  );
}