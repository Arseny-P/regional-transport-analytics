import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Layout from "../layout/Layout";
import { MapView } from "@/widgets/map-view";

export default function AnalysisPage() {

    const navigate = useNavigate();

    const [selectedArea, setSelectedArea] = useState(null);
    const [point1, setPoint1] = useState("");
    const [point2, setPoint2] = useState("");
    const [selectedMode, setSelectedMode] = useState("auto");

    const [isLoading, setIsLoading] = useState(false);
    const [loadingText, setLoadingText] = useState("Подготовка...");

    useEffect(() => {
        if (!isLoading) return;

        const steps = [
            "Загружаем объекты OSM...",
            "Извлекаем координаты...",
            "Строим граф расстояний...",
            "Строим минимальное остовное дерево...",
            "Генерируем карту...",
            "Формируем результаты..."
        ];
        
        let index = 0;
        setLoadingText(steps[index]);

        const interval = setInterval(() => {
            index = (index + 1) % steps.length;
            setLoadingText(steps[index]);
        }, 900);

        return () => clearInterval(interval);
    }, [isLoading]);

    const sidebarContent = (
        <>
            <h3 style={{ marginTop: 0, marginBottom: "16px" }}>Ввод координат</h3>
            <label>
                Точка 1 (lat,lng):
                <input
                    type="text"
                    placeholder="59.88,29.82"
                    value={point1}
                    onChange={(e) => setPoint1(e.target.value)}
                    style={{ width: "100%", marginTop: "4px", padding: "6px 8px", borderRadius: "6px", border: "1px solid #ccc" }}
                />
            </label>
            <label>
                Точка 2 (lat,lng):
                <input
                    type="text"
                    placeholder="59.88,29.83"
                    value={point2}
                    onChange={(e) => setPoint2(e.target.value)}
                    style={{ width: "100%", marginTop: "4px", padding: "6px 8px", borderRadius: "6px", border: "1px solid #ccc" }}
                />
            </label>

            <div style={{ marginTop: "20px" }}>
                <h4 style={{ marginBottom: "8px" }}>Тип маршрута:</h4>

                <label style={{ display: "block", marginBottom: "6px" }}>
                    <input
                        type="radio"
                        name="mode"
                        value="auto"
                        checked={selectedMode === "auto"}
                        onChange={() => setSelectedMode("auto")}
                    />{" "}
                    Автомобильный
                </label>

                <label style={{ display: "block", marginBottom: "6px" }}>
                    <input
                        type="radio"
                        name="mode"
                        value="aero"
                        checked={selectedMode === "aero"}
                        onChange={() => setSelectedMode("aero")}
                    />{" "}
                    Авиационный
                </label>

                <label style={{ display: "block", marginBottom: "6px" }}>
                    <input
                        type="radio"
                        name="mode"
                        value="sea"
                        checked={selectedMode === "sea"}
                        onChange={() => setSelectedMode("sea")}
                    />{" "}
                    Морской
                </label>

                <label style={{ display: "block", marginBottom: "6px"  }}>
                    <input
                        type="radio"
                        name="mode"
                        value="rail"
                        checked={selectedMode === "rail"}
                        onChange={() => setSelectedMode("rail")}
                    />{" "}
                    Железнодорожный
                </label>
                <label style={{ display: "block", marginBottom: "6px" }}>
                    <input
                        type="radio"
                        name="mode"
                        value="all"
                        checked={selectedMode === "all"}
                        onChange={() => setSelectedMode("all")}
                    />{" "}
                    Все режимы
                </label>
            </div>
        </>
    );

    function areaToGeoJSON(area, routemode) {
        return {
            type: "Feature",
            geometry: {
                type: "Polygon",
                coordinates: [[
                    [area.minLng, area.minLat],
                    [area.maxLng, area.minLat],
                    [area.maxLng, area.maxLat],
                    [area.minLng, area.maxLat],
                    [area.minLng, area.minLat],
                ]]
            },
            properties: {
                zoom: area.zoom || null,
                mode: routemode || "auto",
            }
        };
    }

    async function sendGeoJSON(geojson) {
        try {
            const [minLng, minLat] = geojson.geometry.coordinates[0][0];
            const [maxLng, maxLat] = geojson.geometry.coordinates[0][2];
            const mode = geojson.properties.mode;

            const url = `http://localhost:8000/analyze?west=${minLng}&south=${minLat}&east=${maxLng}&north=${maxLat}&mode=${mode}`;

            const response = await fetch(url, { method: "POST" });
        if (!response.ok) throw new Error(`Ошибка сервера: ${response.status}`);

        const data = await response.json();
        return {
            ...data,
            bbox: [minLng, minLat, maxLng, maxLat],
            mode,
        };
    } catch (err) {
        console.error("❌ Ошибка при отправке:", err);
        throw err;
    }
}

    const handleAnalyze = async () => {
        if (!selectedArea) {
            alert("Выделите участок карты для анализа!");
            return;
        }

        setIsLoading(true);

        const geojson = areaToGeoJSON(selectedArea, selectedMode);
        console.log("Отправляем GeoJSON:", geojson);
        try {
            const resultData = await sendGeoJSON(geojson);
            setIsLoading(false);
             navigate("/result", { state: resultData });

        } catch (err) {
            console.error("Ошибка при отправке:", err);
            setIsLoading(false);
            alert("Ошибка при обращении к серверу анализа!");
        }
    };


    return (
        <div style={{ position: "relative", flex: 1, width: "100%", height: "100%", minHeight: 0 }}>

            <Layout sidebarContent={sidebarContent}>

                <MapView
                    onAreaSelect={setSelectedArea}
                    point1={point1}
                    point2={point2}
                    setPoint1={setPoint1}
                    setPoint2={setPoint2}
                />
            </Layout>

            {selectedArea && (
                <button
                    onClick={handleAnalyze}
                    style={{
                        position: "absolute",
                        bottom: "40px",
                        left: "50%",
                        transform: "translateX(-50%)",
                        backgroundColor: "#0f62fe",
                        color: "white",
                        padding: "10px 20px",
                        border: "none",
                        borderRadius: "8px",
                        cursor: "pointer",
                        fontWeight: "bold",
                        boxShadow: "0 2px 6px rgba(0,0,0,0.2)",
                        zIndex: 1000,
                    }}
                >
                    Начать анализ
                </button>
            )}  

            {isLoading && (
                <div style={{
                    position: "fixed",
                    top: 0, left: 0,
                    width: "100%",
                    height: "100%",
                    backgroundColor: "rgba(0,0,0,0.5)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    zIndex: 2000
                }}>
                    <div style={{
                        background: "white",
                        padding: "20px 30px",
                        borderRadius: "10px",
                        boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
                        minWidth: "300px",
                        textAlign: "center",
                        fontSize: "18px",
                        fontWeight: "bold"
                    }}>
                        <div className="loader" style={{
                            width: "40px",
                            height: "40px",
                            border: "4px solid #ccc",
                            borderTop: "4px solid #0f62fe",
                            borderRadius: "50%",
                            margin: "0 auto 16px",
                            animation: "spin 1s linear infinite"
                        }} />
                        {loadingText}
                    </div>

                    <style>
                        {`
                            @keyframes spin {
                                from { transform: rotate(0deg); }
                                to { transform: rotate(360deg); }
                            }
                        `}
                    </style>
                </div>
            )}

            {selectedArea && (
                <div style={{
                    position: "absolute",
                    top: "60px",
                    left: "50%",
                    transform: "translateX(-50%)",
                    backgroundColor: "rgba(255, 255, 255, 0.9)",
                    padding: "6px 12px",
                    borderRadius: "6px",
                    zIndex: 1000,
                    fontWeight: "bold",
                }}>
                    ✅ Область выбрана
                </div>
            )}
        </div>
    );

}