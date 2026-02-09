'use client';

import { Order } from '@/lib/types';

interface OrdersTableProps {
  orders: Order[];
}

export default function OrdersTable({ orders }: OrdersTableProps) {
  const formatPrice = (cents: number | null) => {
    if (cents === null || cents === undefined) return '---';
    return `${cents}c`;
  };

  const formatTime = (timestamp: string | null) => {
    if (!timestamp) return '---';
    return new Date(timestamp).toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getStatusClass = (status: string) => {
    switch (status) {
      case 'resting': return 'text-terminal-cyan-bright';
      case 'executed': return 'text-terminal-green';
      case 'canceled': return 'text-terminal-dim';
      default: return 'text-terminal-dim';
    }
  };

  const getPrice = (order: Order) => order.yes_price ?? order.no_price;

  // Separate resting from historical
  const restingOrders = orders.filter(o => o.status === 'resting');
  const otherOrders = orders.filter(o => o.status !== 'resting');

  if (orders.length === 0) {
    return (
      <div className="panel p-4">
        <div className="border-b border-terminal-green pb-2 mb-4">
          <div className="text-xs text-terminal-dim mb-1">ORDER BOOK</div>
          <div className="text-lg font-bold terminal-glow tracking-wide">ORDERS</div>
        </div>
        <div className="text-center py-8 text-terminal-dim">NO ORDERS</div>
      </div>
    );
  }

  return (
    <div className="panel p-4">
      <div className="border-b border-terminal-green pb-2 mb-4">
        <div className="text-xs text-terminal-dim mb-1">ORDER BOOK</div>
        <div className="flex justify-between items-baseline">
          <div className="text-lg font-bold terminal-glow tracking-wide">ORDERS</div>
          <div className="text-xs text-terminal-dim">
            {restingOrders.length > 0 && <span className="text-terminal-cyan-bright">{restingOrders.length} RESTING</span>}
            {otherOrders.length > 0 && <span className="ml-2">{otherOrders.length} HIST</span>}
          </div>
        </div>
      </div>

      {/* Mobile Card View */}
      <div className="md:hidden space-y-2">
        {orders.map((order) => (
          <div key={order.order_id} className="border border-terminal-green/30 rounded p-3 space-y-1">
            <div className="flex justify-between items-start">
              <div>
                <span className={`text-xs font-bold ${order.action === 'buy' ? 'text-terminal-green' : 'text-terminal-red-bright'}`}>
                  {order.action.toUpperCase()}
                </span>
                <span className={`text-xs ml-1 ${order.side === 'yes' ? 'text-terminal-green' : 'text-terminal-red-bright'}`}>
                  {order.side.toUpperCase()}
                </span>
                <span className="text-xs text-terminal-dim ml-2">x{order.remaining_count}/{order.initial_count}</span>
              </div>
              <span className={`text-xs font-mono ${getStatusClass(order.status)}`}>
                [{order.status.toUpperCase()}]
              </span>
            </div>
            <div className="text-sm text-terminal-green font-mono truncate">{order.ticker}</div>
            <div className="flex justify-between text-[10px] text-terminal-dim">
              <span>PRICE: {formatPrice(getPrice(order))}</span>
              <span>FILLED: {order.fill_count}</span>
              <span>{formatTime(order.created_time)}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Desktop Table View */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="text-terminal-dim border-b border-terminal-green/20">
              <th className="text-left py-2 pr-3">STATUS</th>
              <th className="text-left py-2 px-2">MARKET</th>
              <th className="text-center py-2 px-2">ACTION</th>
              <th className="text-center py-2 px-2">SIDE</th>
              <th className="text-right py-2 px-2">PRICE</th>
              <th className="text-right py-2 px-2">SIZE</th>
              <th className="text-right py-2 px-2">FILLED</th>
              <th className="text-right py-2 px-2">REMAINING</th>
              <th className="text-right py-2 px-2">FEES</th>
              <th className="text-right py-2 pl-2">TIME</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr key={order.order_id} className="border-b border-terminal-green/10 hover:bg-terminal-green/5 transition-colors">
                <td className={`py-2 pr-3 ${getStatusClass(order.status)}`}>
                  [{order.status.toUpperCase()}]
                </td>
                <td className="py-2 px-2 text-terminal-green max-w-[180px] truncate" title={order.ticker}>
                  {order.ticker}
                </td>
                <td className={`py-2 px-2 text-center font-bold ${order.action === 'buy' ? 'text-terminal-green' : 'text-terminal-red-bright'}`}>
                  {order.action.toUpperCase()}
                </td>
                <td className={`py-2 px-2 text-center ${order.side === 'yes' ? 'text-terminal-green' : 'text-terminal-red-bright'}`}>
                  {order.side.toUpperCase()}
                </td>
                <td className="py-2 px-2 text-right">{formatPrice(getPrice(order))}</td>
                <td className="py-2 px-2 text-right">{order.initial_count}</td>
                <td className="py-2 px-2 text-right">{order.fill_count}</td>
                <td className="py-2 px-2 text-right">{order.remaining_count}</td>
                <td className="py-2 px-2 text-right text-terminal-dim">
                  {(order.taker_fees + order.maker_fees) > 0 ? `${((order.taker_fees + order.maker_fees) / 100).toFixed(2)}` : '---'}
                </td>
                <td className="py-2 pl-2 text-right text-terminal-dim">{formatTime(order.created_time)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
