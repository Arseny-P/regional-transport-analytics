import unittest
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon, Point

from graph_service.domain import GraphRole, VerificationStatus, LogisticsNode
from graph_service.algorithms import FacilityService


class TestFacilityClassification(unittest.TestCase):
    def setUp(self):
        self.facility_service = FacilityService()

    def test_exclude_passenger_depot_and_station(self):
        """
        Проверяет отсечение пассажирских депо (bus/tram/subway)
        и пассажирских ж/д станций без грузовых признаков (п. 3.2).
        """
        data = [
            # 1. Автобусное депо -> должно быть отфильтровано
            {
                "name": "Автобусный парк №1",
                "industrial": "depot",
                "depot": "bus",
                "geometry": Point(30.3, 59.9),
            },
            # 2. Метродепо -> должно быть отфильтровано
            {
                "name": "Электродепо Автово",
                "industrial": "depot",
                "depot": "subway",
                "geometry": Point(30.2, 59.8),
            },
            # 3. Пассажирская станция без грузовых признаков -> должна быть отфильтрована
            {
                "name": "Станция Метро / Вокзал",
                "railway": "station",
                "geometry": Point(30.3, 59.9),
            },
            # 4. Грузовая станция / сортировочная -> должна быть включена
            {
                "name": "Санкт-Петербург-Сортировочный-Московский",
                "railway": "station",
                "cargo": "freight",
                "geometry": Point(30.4, 59.85),
            },
            # 5. Грузовая погрузочная рампа -> должна быть включена
            {
                "name": "Погрузочная рампа Северная",
                "railway": "loading_ramp",
                "geometry": Point(30.42, 59.86),
            },
        ]
        gdf = gpd.GeoDataFrame(data, geometry="geometry", index=[
            ("way", 101),
            ("way", 102),
            ("node", 103),
            ("relation", 104),
            ("way", 105),
        ])

        nodes = self.facility_service._extract_nodes_from_gdf(gdf=gdf, limit=10)

        # Должны остаться только грузовая станция и погрузочная рампа
        self.assertEqual(len(nodes), 2)
        names = [n.name for n in nodes]
        self.assertIn("Санкт-Петербург-Сортировочный-Московский", names)
        self.assertIn("Погрузочная рампа Северная", names)

        # Проверяем типизированный OSM ID
        cargo_node = next(n for n in nodes if "Сортировочный" in n.name)
        self.assertEqual(cargo_node.source_osm_ids[0], "osm:relation/104")

    def test_generic_landuse_industrial_filter(self):
        """
        Проверяет, что безымянная общая промзона landuse=industrial без логистических ключевых слов
        не создается как самостоятельный логистический узел (п. 3.1 & 3.2).
        """
        data = [
            # Безымянная промзона без признаков логистики
            {
                "landuse": "industrial",
                "geometry": Polygon([(30.0, 59.0), (30.1, 59.0), (30.1, 59.1), (30.0, 59.1)]),
            },
            # Именованный складской комплекс в промзоне
            {
                "name": "Логистический парк Шушары",
                "landuse": "industrial",
                "industrial": "logistics",
                "geometry": Polygon([(30.2, 59.0), (30.3, 59.0), (30.3, 59.1), (30.2, 59.1)]),
            },
        ]
        gdf = gpd.GeoDataFrame(data, geometry="geometry", index=[("way", 201), ("relation", 202)])
        nodes = self.facility_service._extract_nodes_from_gdf(gdf=gdf, limit=10)

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].name, "Логистический парк Шушары")
        self.assertEqual(nodes[0].identification_basis["tag_strength"], "strong")
        self.assertEqual(nodes[0].verification_status, VerificationStatus.VERIFIED.value)

    def test_building_within_site_hierarchy(self):
        """
        Проверяет п. 3.3 (Разделение здания и комплекса):
        Складское здание внутри полигона логистического парка привязывается к parent_site_id
        и получает graph_role = nested_candidate, сохраняясь в реестре.
        """
        # Полигон площадки комплекса (от 30.0 до 30.1 по lon, от 59.0 до 59.1 по lat)
        site_poly = Polygon([(30.0, 59.0), (30.1, 59.0), (30.1, 59.1), (30.0, 59.1)])
        
        # Складское здание внутри площадки (от 30.02 до 30.04)
        nested_bld_poly = Polygon([(30.02, 59.02), (30.04, 59.02), (30.04, 59.04), (30.02, 59.04)])

        # Отдельное самостоятельное здание склада снаружи площадки (от 30.5 до 30.6)
        standalone_bld_poly = Polygon([(30.5, 59.5), (30.6, 59.5), (30.6, 59.6), (30.5, 59.6)])

        data = [
            {
                "name": "Логистический комплекс Норд",
                "industrial": "logistics",
                "geometry": site_poly,
            },
            {
                "name": "Склад Корпус 1",
                "building": "warehouse",
                "geometry": nested_bld_poly,
            },
            {
                "name": "Отдельный складской терминал",
                "building": "warehouse",
                "geometry": standalone_bld_poly,
            },
        ]
        gdf = gpd.GeoDataFrame(data, geometry="geometry", index=[
            ("relation", 301),
            ("way", 302),
            ("way", 303),
        ])

        nodes = self.facility_service._extract_nodes_from_gdf(gdf=gdf, limit=10)
        self.assertEqual(len(nodes), 3)

        site_node = next(n for n in nodes if "Норд" in n.name)
        nested_node = next(n for n in nodes if "Корпус 1" in n.name)
        standalone_node = next(n for n in nodes if "Отдельный" in n.name)

        # 1. Проверяем площадку
        self.assertEqual(site_node.graph_role, GraphRole.NODE_CANDIDATE.value)
        self.assertIsNone(site_node.parent_site_id)
        # Площадка должна зафиксировать содержащееся здание
        self.assertIn("contains_buildings", site_node.identification_basis)
        self.assertIn(nested_node.source_osm_ids[0], site_node.identification_basis["contains_buildings"])

        # 2. Проверяем вложенное здание
        self.assertEqual(nested_node.graph_role, GraphRole.NESTED_CANDIDATE.value)
        self.assertEqual(nested_node.parent_site_id, site_node.id)
        self.assertIn("located_within", nested_node.identification_basis["spatial_relation"])

        # 3. Проверяем самостоятельное отдельное здание
        self.assertEqual(standalone_node.graph_role, GraphRole.NODE_CANDIDATE.value)
        self.assertIsNone(standalone_node.parent_site_id)


if __name__ == "__main__":
    unittest.main()
