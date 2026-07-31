using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Store.Catalog.Migrations
{
    /// <inheritdoc />
    public partial class AddPackDelistReason : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "DelistReason",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<DateTime>(
                name: "DelistedAt",
                table: "Packs",
                type: "TEXT",
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "DelistReason",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "DelistedAt",
                table: "Packs");
        }
    }
}
