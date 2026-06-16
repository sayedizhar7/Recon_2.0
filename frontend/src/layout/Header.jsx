import { Bell, Search } from "lucide-react";

export default function Header() {

  const today = new Date().toLocaleString();

  return (
    <div className="flex items-center justify-between bg-white px-6 py-4 shadow-sm rounded-xl mb-6">

      {/* ✅ LEFT SIDE — Title */}
      <div>
        <h1 className="text-2xl font-semibold text-gray-800">
          Reconciliation Dashboard
        </h1>
        <p className="text-sm text-gray-500">
          Monitor matches, performance, and insights
        </p>
      </div>

      {/* ✅ CENTER — SEARCH */}
      <div className="hidden md:flex items-center bg-gray-100 rounded-lg px-3 py-2 w-72">

        <Search size={18} className="text-gray-400 mr-2" />

        <input
          type="text"
          placeholder="Search transactions..."
          className="bg-transparent outline-none w-full text-sm"
        />

      </div>

      {/* ✅ RIGHT SIDE */}
      <div className="flex items-center gap-4">

        {/* ✅ Date */}
        <span className="text-sm text-gray-500 hidden lg:block">
          {today}
        </span>

        {/* ✅ Notifications */}
        <div className="relative cursor-pointer">
          <Bell className="text-gray-600" size={20} />

          <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs px-1 rounded-full">
            3
          </span>
        </div>

        {/* ✅ Profile */}
        <div className="flex items-center gap-2 cursor-pointer">

          <div className="w-8 h-8 bg-blue-500 text-white flex items-center justify-center rounded-full">
            A
          </div>

          <span className="text-sm font-medium hidden md:block">
            Admin
          </span>

        </div>

      </div>

    </div>
  );
}
