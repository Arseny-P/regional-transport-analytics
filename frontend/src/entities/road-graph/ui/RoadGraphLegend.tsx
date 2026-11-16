import { REGIONS_CONFIG } from '../config/regions';

export function RoadGraphLegend() {
  return (
    <div style={{ 
      position: 'absolute', bottom: '20px', right: '20px', 
      backgroundColor: 'white', padding: '15px', borderRadius: '8px', 
      boxShadow: '0 2px 8px rgba(0,0,0,0.3)', zIndex: 1000, fontSize: '14px',
      minWidth: '180px'
    }}>
      <div style={{ marginBottom: '10px', fontWeight: 'bold' }}>Легенда:</div>
      {REGIONS_CONFIG.map((region) => (
        <div key={region.id} style={{ marginBottom: '12px', borderBottom: '1px solid #eee', paddingBottom: '8px' }}>
          <div style={{ fontWeight: '600', color: region.color, marginBottom: '6px' }}>{region.label}:</div>
          
          {/* Логистические объекты (точки) */}
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
            <div style={{ 
              width: '12px', height: '12px', borderRadius: '50%', 
              backgroundColor: region.pointColor, border: '2px solid white', 
              boxShadow: '0 0 0 1px rgba(0,0,0,0.2)', marginRight: '8px' 
            }}></div>
            <span>Логистические объекты</span>
          </div>
          
          {/* Транспортные связи (линии) */}
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{ 
              width: '24px', height: '3px', backgroundColor: region.color, 
              marginRight: '8px', borderRadius: '2px'
            }}></div>
            <span>Транспортные связи</span>
          </div>
        </div>
      ))}
    </div>
  );
}