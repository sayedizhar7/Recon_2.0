import { BarChart, Bar, XAxis, YAxis } from "recharts";

export default function Charts({ data }) {
  return (
    <BarChart width={400} height={300} data={data}>
      <XAxis dataKey="layer" />
      <YAxis />
      <Bar dataKey="count" fill="#3b82f6" />
    </BarChart>
  );
}