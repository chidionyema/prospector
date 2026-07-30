using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Store.Catalog.Migrations
{
    /// <inheritdoc />
    public partial class AddPackFacets : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "AdvantagesJson",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "Commitment",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "Effort",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "Mechanism",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "Payer",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "Sector",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.CreateIndex(
                name: "IX_Packs_Effort",
                table: "Packs",
                column: "Effort");

            migrationBuilder.CreateIndex(
                name: "IX_Packs_Mechanism",
                table: "Packs",
                column: "Mechanism");

            migrationBuilder.CreateIndex(
                name: "IX_Packs_Payer",
                table: "Packs",
                column: "Payer");

            migrationBuilder.CreateIndex(
                name: "IX_Packs_Sector",
                table: "Packs",
                column: "Sector");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_Packs_Effort",
                table: "Packs");

            migrationBuilder.DropIndex(
                name: "IX_Packs_Mechanism",
                table: "Packs");

            migrationBuilder.DropIndex(
                name: "IX_Packs_Payer",
                table: "Packs");

            migrationBuilder.DropIndex(
                name: "IX_Packs_Sector",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "AdvantagesJson",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "Commitment",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "Effort",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "Mechanism",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "Payer",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "Sector",
                table: "Packs");
        }
    }
}
