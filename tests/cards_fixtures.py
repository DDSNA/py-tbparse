"""A small workbook for the Dashboards cards: a mixed dashboard, one with no stored positions, one with many zones,
and (optionally) many dashboards, so paging can be tried."""

from __future__ import annotations


def cards_workbook(many_zones: int = 60, extra_dashboards: int = 0) -> str:
    many = "".join(
        f"<zone id='{100 + i}' name='Sheet {i % 3 + 1}' x='{(i % 10) * 10000}' y='{(i // 10) * 5000}' "
        f"w='{1000 + i * 10}' h='{1000 + i * 10}'/>" for i in range(many_zones))
    extra = "".join(
        f"<dashboard name='Extra {i:03d}'><size minwidth='800' minheight='600' maxwidth='800' maxheight='600'/>"
        f"<zones><zone id='1' name='Sheet 1' x='0' y='0' w='100000' h='100000'/></zones></dashboard>"
        for i in range(extra_dashboards))
    return f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1'>
  <datasources>
    <datasource name='Parameters' hasconnection='false'>
      <column caption='Top N' name='[Parameter 1]' datatype='integer' param-domain-type='range' role='measure'>
        <calculation class='tableau' formula='5' />
      </column>
    </datasource>
    <datasource name='ds1'><column name='[Region]' datatype='string' role='dimension' /></datasource>
  </datasources>
  <worksheets>
    <worksheet name='Sheet 1'><table><view /></table></worksheet>
    <worksheet name='Sheet 2'><table><view /></table></worksheet>
    <worksheet name='Sheet 3'><table><view /></table></worksheet>
  </worksheets>
  <dashboards>
    <dashboard name="Mixed 'one'">
      <size minwidth='1200' minheight='800' maxwidth='1200' maxheight='800'/>
      <zones>
        <zone id='1' type-v2='layout-flow' param='vert' x='0' y='0' w='100000' h='100000'>
          <zone id='2' type-v2='bitmap' x='0' y='0' w='12000' h='8000'/>
          <zone id='3' type-v2='text' x='12000' y='0' w='88000' h='8000'/>
          <zone id='4' name='Sheet 1' x='0' y='8000' w='60000' h='52000'/>
          <zone id='5' name='Sheet 2' x='60000' y='8000' w='40000' h='52000'/>
          <zone id='6' type-v2='filter' name='Sheet 1' param='[ds1].[none:Region:nk]' x='0' y='60000' w='25000' h='40000'/>
          <zone id='7' type-v2='paramctrl' param='[Parameters].[Parameter 1]' x='25000' y='60000' w='25000' h='40000'/>
          <zone id='8' type-v2='web' x='50000' y='60000' w='50000' h='40000'/>
        </zone>
      </zones>
      <devicelayouts><devicelayout name='Phone'><zones>
        <zone id='99' name='Sheet 2' x='0' y='0' w='100000' h='100000'/>
      </zones></devicelayout></devicelayouts>
    </dashboard>
    <dashboard name='No positions'>
      <zones><zone id='1' type-v2='layout-basic'/></zones>
    </dashboard>
    <dashboard name='Many zones'><zones>{many}</zones></dashboard>
    {extra}
  </dashboards>
</workbook>
"""
